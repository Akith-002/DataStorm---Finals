from flask import Flask, request, render_template, jsonify, g
import os
import re
import sqlite3
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Load environment variables from key.env file
load_dotenv(dotenv_path='key.env')

# Initialize OpenAI client with your API key
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Connect to SQLite database
db_file_path = 'customer_data.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(db_file_path)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def add_csv_to_db(csv_file_path, table_name):
    df = pd.read_csv(csv_file_path)
    # Convert customer_code to integer if it exists
    if 'customer_code' in df.columns:
        df['customer_code'] = df['customer_code'].astype(int)
    with app.app_context():
        df.to_sql(table_name, get_db(), if_exists='replace', index=False)
        print(f"CSV data has been successfully written to {table_name} table.")


# Add the customer_category.csv file
customer_category_csv = 'files/customer_category.csv'
add_csv_to_db(customer_category_csv, 'customer_category')

# Add the item_category_product_sales.csv file
item_category_product_sales_csv = 'files/item_category_product_sales.csv'
add_csv_to_db(item_category_product_sales_csv, 'item_category_product_sales')

# Add the most_brought_items_by_each_customer_per_day.csv file
most_brought_items_csv = 'files/most_bought_items_by_each_customer_per_day.csv'
add_csv_to_db(most_brought_items_csv, 'most_brought_items')

# Add the each_customer_segmentwise_most_bought.csv file
each_customer_segmentwise_most_bought_csv = 'files/each_customer_segmentwise_most_bought.csv'
add_csv_to_db(each_customer_segmentwise_most_bought_csv, 'each_customer_segmentwise_most_bought')

# Define a dictionary to store customer categories and their preferred product categories
customer_category_preferences = {
    'Frozen Meat and Seafood Enthusiasts': ('frozen_meat', 'seafood'),
    'Wellness Seekers': ('wellness_food', 'wellness_products'),
    'Diverse Shoppers': ('frozen_meat', 'seafood', 'stationery', 'fruits', 'vegetables', 'pet_care'),
    'Fresh Produce Lovers': ('fruits', 'vegetables'),
    'Dairy Aficionados': ['dairy'],
    'Beauty and Personal Care Enthusiasts': ['beauty_and_personal_care'],
    'Baby Needs Shoppers': ['baby_needs']
}

# Define routes
@app.route('/', methods=['GET', 'POST'])
def index():
    # For GET requests or initial page load, render the test.html template
    return render_template('test.html')

@app.route('/ask', methods=['POST'])
def ask():
    # Get user input from the form
    user_input = request.form['user_input']

    # Split the user input into customer code and function number
    try:
        customer_code, function_number = map(int, user_input.split())
    except ValueError:
        return jsonify({"response": "Please enter a valid customer code and a select a function from the dropdown list."})

    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM customer_category WHERE customer_code = ?", (customer_code,))
    customer = cursor.fetchone()

    if customer:
        # If the customer code is valid, call the corresponding function
        response = generate_response(customer_code, function_number)
    else:
        response = "Please enter a valid customer code."

    return jsonify({"response": response})

def format_message(message):
    # Convert markdown-like formatting to HTML
    message = re.sub(r'\*(.*?)\*', r'<strong>\1</strong>', message)  # Bold text
    message = re.sub(r'_(.*?)_', r'<em>\1</em>', message)  # Italics
    message = re.sub(r'### (.*?)\n', r'<h3>\1</h3>', message)  # Headers
    message = re.sub(r'1\.\s', r'<br>1. ', message)  # List items with numbers
    message = re.sub(r'\n', r'<br>', message)  # New lines to <br> tags
    return message


def generate_response(customer_id, function_number):
    try:
        cursor = get_db().cursor()
        cursor.execute("SELECT segment FROM customer_category WHERE customer_code = ?", (customer_id,))
        customer_category = cursor.fetchone()[0]
    except Exception as e:
        print(f"Error executing SQL query: {e}")
        return "An error occurred while fetching customer data."

    preferred_product_categories = customer_category_preferences.get(customer_category, [])

    if preferred_product_categories:
        prompt = (
            "You are a virtual business assistant. "
            "Generate a response based on the following information.\n"
        )

        for category in preferred_product_categories:
            cursor.execute("""
                SELECT most_sold, second_most_sold, third_most_sold,
                       least_sold, second_least_sold, third_least_sold
                FROM item_category_product_sales
                WHERE item_category = ?
            """, (category,))
            items = cursor.fetchone()

            if items:
                prompt += f"\nFor {category.replace('_', ' ').title()}:\n"
                prompt += f"Most Sold: {items[0]}\n"
                prompt += f"Second Most Sold: {items[1]}\n"
                prompt += f"Third Most Sold: {items[2]}\n"
                prompt += f"Least Sold: {items[3]}\n"
                prompt += f"Second Least Sold: {items[4]}\n"
                prompt += f"Third Least Sold: {items[5]}\n"
            else:
                prompt += f"\nFor {category.replace('_', ' ').title()}:\nNo items found.\n"

        if function_number == 1:
            prompt += "\nBased on the above data, recommend products to the customer in an organized manner. Do not add any additional details. Make the recommending product order and the number of the products shown random"
        elif function_number == 2:
            # Fetch current day of the week
            current_day = datetime.now().strftime("%A")

            # Fetch most bought item for the current day
            cursor.execute("""
                SELECT most_bought_item_category
                FROM most_brought_items
                WHERE customer_code = ? AND day_of_week = ?
            """, (customer_id, current_day))
            most_bought_item_category = cursor.fetchone()[0]

            # Fetch most bought, second most bought, third most bought, and fourth most bought items for the customer's category
            cursor.execute("""
                SELECT most_bought, second_most_bought, third_most_bought, fourth_most_bought
                FROM each_customer_segmentwise_most_bought
                WHERE customer_code = ? AND segment = ?
            """, (customer_id, customer_category))
            items = cursor.fetchone()

            prompt += (
                f"Generate a personalized shopping list for {customer_category}. "
                f"For today, the most bought item is {most_bought_item_category}. "
                f"Include the following items in your list: {items[0]}, {items[1]}, {items[2]}, {items[3]}. "
                "Present the list in a clear, enthusiastic and organized manner, without any additional formatting or descriptions."
            )

        elif function_number == 3:
            prompt += "\nGenerate a promotional message based on the above data. Tell the user if they buy 2 least sold items and a most sold item, they will get a discount. Generate a random discount amount and present the offer attractively yet simply and organized. Do not mention about the most sold or least sold details seperateli like thse are the most sold and these are least sold"
            
        else:
            return "Please enter a valid function number."

        # Use the OpenAI API to get the response
        try:
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a virtual business assistant providing product recommendations, tailored promotions, and personalized shopping lists for supermarket customers. Your responses should be concise, organized, and focused on the provided data."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500,
                top_p=1,
                frequency_penalty=1,
                presence_penalty=0
            )

            response = completion.choices[0].message.content
            # Format the response to replace markdown with HTML
            response = format_message(response)
        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return "An error occurred while generating the response."
    else:
        response = f"No preferred product categories found for customer {customer_id}."

    return response

# Run Flask app
if __name__ == '__main__':
    app.run(debug=True)

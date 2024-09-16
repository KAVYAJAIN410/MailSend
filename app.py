from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, current_app
from pymongo import MongoClient, ReturnDocument
from werkzeug.security import generate_password_hash, check_password_hash
import yagmail
import uuid
import csv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Initialize Flask App
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.secret_key = 'your_secret_key'  # Required for flash messages

# MongoDB client and database setup
client = MongoClient('mongodb+srv://iamaipalendrome:<db_password>@cluster0.clrz1.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
db = client['email_db']
users_collection = db['users']
bulk_email_instances_collection = db['bulk_email_instances']
email_tracking_collection = db['email_tracking']

# Ensure indexes for unique fields
users_collection.create_index('username', unique=True)
email_tracking_collection.create_index([('email', 1), ('bulk_email_id', 1)], unique=True)

# Helper functions for MongoDB queries
def find_user(username):
    return users_collection.find_one({'username': username})

def create_user(username, password_hash):
    user = {
        'username': username,
        'password_hash': password_hash,
        'yagmail_user': None,
        'yagmail_password': None,
        'email_settings_completed': False
    }
    return users_collection.insert_one(user)

def find_bulk_email_instance(bulk_email_id):
    return bulk_email_instances_collection.find_one({'_id': bulk_email_id})

# Email sending function
def send_email(yagmail_user, yagmail_password, email, row, subject_template, content_template, tracking_url, bulk_email_id):
    unique_id = str(uuid.uuid4())
    subject = replace_tags(subject_template, row)
    contents = replace_tags(content_template, row) + f'<img src="{tracking_url}" alt="Tracking Pixel" style="display:none;"/>'

    yag = yagmail.SMTP(yagmail_user, yagmail_password)

    try:
        yag.send(to=email, subject=subject, contents=[contents])

        # Log the email status in the database
        email_tracking_collection.find_one_and_update(
            {'email': email, 'bulk_email_id': bulk_email_id},
            {'$set': {
                'id': unique_id,
                'name': row['name'],
                'opened': False,
                'sent': True
            }},
            upsert=True
        )
        return None  # No error
    except Exception as e:
        return {'email': email, 'name': row['name'], 'error': str(e)}

# Replace template placeholders with actual values
def replace_tags(template, row):
    for key, value in row.items():
        template = template.replace(f"{{{{{key}}}}}", value)
    return template

# Log email open event
def log_email_open(id):
    email_tracking_collection.find_one_and_update(
        {'_id': id},
        {'$set': {'opened': True}},
        return_document=ReturnDocument.AFTER
    )

# Track email opening via pixel
@app.route('/track/<id>.png')
def track_email(id):
    log_email_open(id)
    return send_file('tracking_pixel.png', mimetype='image/png')

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('home'))
    return redirect(url_for('dashboard'))

@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = find_user(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user'] = username
            if not user.get('email_settings_completed'):
                return redirect(url_for('email_settings'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if find_user(username):
            flash('Username already exists')
        else:
            password_hash = generate_password_hash(password)
            create_user(username, password_hash)
            flash('Signup successful, please login')
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('home'))
    user = find_user(session['user'])
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    bulk_emails = bulk_email_instances_collection.find({'user_id': user['_id']})
    return render_template('dashboard.html', user=user, bulk_emails=bulk_emails)

@app.route('/email_settings', methods=['GET', 'POST'])
def email_settings():
    if 'user' not in session:
        return redirect(url_for('home'))
    user = find_user(session['user'])
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    if request.method == 'POST':
        yagmail_user = request.form['yagmail_user']
        yagmail_password = request.form['yagmail_password']
        users_collection.find_one_and_update(
            {'username': session['user']},
            {'$set': {
                'yagmail_user': yagmail_user,
                'yagmail_password': yagmail_password,
                'email_settings_completed': True
            }}
        )
        flash('Email settings updated successfully')
        return redirect(url_for('dashboard'))
    return render_template('email_settings.html', user=user)

@app.route('/send_bulk_email/<int:bulk_email_id>', methods=['GET', 'POST'])
def send_bulk_email(bulk_email_id):
    if 'user' not in session:
        return redirect(url_for('home'))

    user = find_user(session['user'])
    bulk_email = find_bulk_email_instance(bulk_email_id)

    if not user['yagmail_user'] or not user['yagmail_password']:
        flash('Email settings are required before sending emails.')
        return redirect(url_for('email_settings'))

    with open(bulk_email['csv_file'], mode='r') as file:
        reader = csv.DictReader(file)
        email_tasks = []
        tracking_url_base = url_for('track_email', id=str(uuid.uuid4()), _external=True)

        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=10) as executor:
            for row in reader:
                email = row['email']

                # Check if email already sent
                existing_tracking = email_tracking_collection.find_one({'email': email, 'bulk_email_id': bulk_email_id})
                if existing_tracking and existing_tracking.get('sent'):
                    continue  # Skip if already sent

                tracking_url = tracking_url_base.replace(str(uuid.uuid4()), str(uuid.uuid4()))
                future = executor.submit(
                    send_email,
                    user['yagmail_user'],
                    user['yagmail_password'],
                    email,
                    row,
                    bulk_email['subject_template'],
                    bulk_email['content_template'],
                    tracking_url,
                    bulk_email_id
                )
                email_tasks.append(future)

            # Collect results and handle errors
            for future in as_completed(email_tasks):
                error = future.result()
                if error:
                    flash(f"Failed to send email to {error['email']}. Error: {error['error']}")

    flash('Emails have been sent!')
    return redirect(url_for('email_report', bulk_email_id=bulk_email_id))

@app.route('/email_report/<int:bulk_email_id>', methods=['GET'])
def email_report(bulk_email_id):
    if 'user' not in session:
        return redirect(url_for('content', page='home'))
    user = find_user(session['user'])
    bulk_email = find_bulk_email_instance(bulk_email_id)

    # Retrieve tracking data
    tracking_data = list(email_tracking_collection.find({'bulk_email_id': bulk_email_id}))

    # Handle filter option
    filter_option = request.args.get('filter', 'all')
    if filter_option == 'success':
        tracking_data = [tracking for tracking in tracking_data if tracking.get('opened')]
    elif filter_option == 'failed':
        tracking_data = [tracking for tracking in tracking_data if not tracking.get('opened')]

    return render_template('email_report.html', tracking_data=tracking_data, bulk_email=bulk_email, filter=filter_option)

if __name__ == '__main__':
    app.run(debug=True)

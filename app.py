from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, current_app
import yagmail
import csv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://sql12721518:sKDMJWv5a3@sql12.freesqldatabase.com:3306/sql12721518'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'  # Required for flash messages

db = SQLAlchemy(app)

# User model
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    yagmail_user = db.Column(db.String(120))
    yagmail_password = db.Column(db.String(120))
    bulk_emails = db.relationship('BulkEmailInstance', backref='user', lazy=True)

# Bulk email instance model
class BulkEmailInstance(db.Model):
    __tablename__ = 'bulk_email_instances'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    subject_template = db.Column(db.String(200))
    content_template = db.Column(db.Text)
    csv_file = db.Column(db.String(200))
    email_trackings = db.relationship('EmailTracking', backref='bulk_email_instance', lazy=True)

# Email tracking model
class EmailTracking(db.Model):
    __tablename__ = 'email_tracking'
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    opened = db.Column(db.Boolean, default=False)
    bulk_email_id = db.Column(db.Integer, db.ForeignKey('bulk_email_instances.id'), nullable=False)

# Initialize the database
with app.app_context():
    db.create_all()

def log_email_open(id):
    app.logger.info(f"Tracking pixel accessed for ID: {id}")
    try:
        email_tracking = EmailTracking.query.get(id)
        if email_tracking:
            app.logger.info(f"EmailTracking entry found for ID: {id}")
            email_tracking.opened = True
            db.session.commit()
            app.logger.info(f"EmailTracking entry updated for ID: {id}")
        else:
            app.logger.warning(f"No EmailTracking entry found for ID: {id}")
    except Exception as e:
        app.logger.error(f"Error updating EmailTracking entry for ID: {id}. Error: {e}")

@app.route('/track/<id>.png')
def track_email(id):
    log_email_open(id)
    return send_file('tracking_pixel.png', mimetype='image/png')

def replace_tags(template, row):
    app.logger.info(f"Original template: {template}")
    app.logger.info(f"Row data: {row}")
    for key, value in row.items():
        template = template.replace(f"{{{{ {key} }}}}", value)
    app.logger.info(f"Processed template: {template}")
    return template

def send_email(yagmail_user, yagmail_password, email, row, subject_template, content_template, tracking_url, bulk_email_id):
    unique_id = str(uuid.uuid4())
    subject = replace_tags(subject_template, row)
    contents = replace_tags(content_template, row) + f'<img src="{tracking_url}" alt="Tracking Pixel" style="display:none;"/>'

    yag = yagmail.SMTP(yagmail_user, yagmail_password)

    try:
        yag.send(to=email, subject=subject, contents=[contents])
        with app.app_context():
            app.logger.info(f"Email sent to {row['name']} at {email}")
            app.logger.info(f"Tracking URL embedded in email: {tracking_url}")

            email_tracking = EmailTracking(id=unique_id, email=email, name=row['name'], bulk_email_id=bulk_email_id)
            db.session.add(email_tracking)
            db.session.commit()

        return None  # No error
    except Exception as e:
        with app.app_context():
            app.logger.error(f"Failed to send email to {row['name']} at {email}. Error: {e}")
        return {'email': email, 'name': row['name'], 'error': str(e)}

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            password_hash = generate_password_hash(password)
            new_user = User(username=username, password_hash=password_hash)
            db.session.add(new_user)
            db.session.commit()
            flash('Signup successful, please login')
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    bulk_emails = BulkEmailInstance.query.filter_by(user_id=user.id).all()
    return render_template('dashboard.html', user=user, bulk_emails=bulk_emails)

@app.route('/email_settings', methods=['GET', 'POST'])
def email_settings():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    if request.method == 'POST':
        yagmail_user = request.form['yagmail_user']
        yagmail_password = request.form['yagmail_password']
        user.yagmail_user = yagmail_user
        user.yagmail_password = yagmail_password
        db.session.commit()
        flash('Email settings updated successfully')
        return redirect(url_for('dashboard'))
    return render_template('email_settings.html', user=user)

@app.route('/create_bulk_email', methods=['GET', 'POST'])
def create_bulk_email():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        csv_file = request.files.get('csv_file')
        if not name or not csv_file:
            flash('All fields are required.')
            return redirect(url_for('create_bulk_email'))

        # Save the CSV file and extract column names
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_file.filename)
        csv_file.save(file_path)

        with open(file_path, mode='r') as file:
            reader = csv.DictReader(file)
            tags = reader.fieldnames

        bulk_email = BulkEmailInstance(user_id=user.id, name=name, csv_file=file_path)
        db.session.add(bulk_email)
        db.session.commit()

        return redirect(url_for('bulk_email', bulk_email_id=bulk_email.id, tags=','.join(tags)))
    return render_template('create_bulk_email.html')

@app.route('/bulk_email/<int:bulk_email_id>', methods=['GET', 'POST'])
def bulk_email(bulk_email_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    bulk_email = BulkEmailInstance.query.get_or_404(bulk_email_id)
    tags = []
    if bulk_email.csv_file:
        with open(bulk_email.csv_file, mode='r') as file:
            reader = csv.DictReader(file)
            tags = reader.fieldnames
    if request.method == 'POST':
        subject_template = request.form['subject']
        content_template = request.form['content']
        csv_file = request.files.get('csv_file')
        if not subject_template or not content_template:
            flash('All fields are required.')
            return redirect(url_for('bulk_email', bulk_email_id=bulk_email_id))
        if csv_file:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_file.filename)
            csv_file.save(file_path)
            bulk_email.csv_file = file_path
            with open(file_path, mode='r') as file:
                reader = csv.DictReader(file)
                tags = reader.fieldnames
        bulk_email.subject_template = subject_template
        bulk_email.content_template = content_template
        db.session.commit()
        return redirect(url_for('send_bulk_email', bulk_email_id=bulk_email.id))
    return render_template('bulk_email.html', bulk_email=bulk_email, tags=','.join(tags))

@app.route('/send_bulk_email/<int:bulk_email_id>', methods=['GET', 'POST'])
def send_bulk_email(bulk_email_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    bulk_email = BulkEmailInstance.query.get_or_404(bulk_email_id)
    if not user.yagmail_user or not user.yagmail_password:
        flash('Email settings are required before sending emails.')
        return redirect(url_for('email_settings'))
    failed_emails = []
    with open(bulk_email.csv_file, mode='r') as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames  # Get column headers for placeholders
        email_tasks = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            for row in reader:
                email = row['email']
                tracking_url = url_for('track_email', id=str(uuid.uuid4()), _external=True)
                email_tasks.append(
                    executor.submit(send_email, user.yagmail_user, user.yagmail_password, email, row, bulk_email.subject_template, bulk_email.content_template, tracking_url, bulk_email.id)
                )
            for future in as_completed(email_tasks):
                result = future.result()
                if result:
                    failed_emails.append(result)
    return render_template('result.html', failed_emails=failed_emails)

@app.route('/report/<int:bulk_email_id>')
def report(bulk_email_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if user is None:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))
    bulk_email = BulkEmailInstance.query.get_or_404(bulk_email_id)
    tracking_data = EmailTracking.query.filter_by(bulk_email_id=bulk_email_id).all()
    return render_template('report.html', tracking_data=tracking_data, bulk_email=bulk_email)

@app.route('/get_csv_headers/<int:bulk_email_id>')
def get_csv_headers(bulk_email_id):
    bulk_email = BulkEmailInstance.query.get_or_404(bulk_email_id)
    headers = []
    if bulk_email.csv_file:
        with open(bulk_email.csv_file, mode='r') as file:
            reader = csv.DictReader(file)
            headers = reader.fieldnames
    return {'headers': headers}


if __name__ == '__main__':
    app.run(debug=True)

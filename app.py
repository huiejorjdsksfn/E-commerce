import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import stripe
import datetime
import logging
from functools import wraps
import secrets

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True, origins=os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(','))

# Configuration
app.config.update({
    'SECRET_KEY': os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32)),
    'STRIPE_SECRET_KEY': os.getenv('STRIPE_SECRET_KEY'),
    'STRIPE_PUBLIC_KEY': os.getenv('STRIPE_PUBLIC_KEY'),
    'ENVIRONMENT': os.getenv('ENVIRONMENT', 'development')
})

# Configure Stripe
stripe.api_key = app.config['STRIPE_SECRET_KEY']
stripe.api_version = '2023-08-16'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sample database
equipment_db = {
    "excavator": {"name": "Excavator", "price_per_day": 5000, "available": True},
    "bulldozer": {"name": "Bulldozer", "price_per_day": 4500, "available": True},
    "crane": {"name": "Crane", "price_per_day": 6000, "available": True}
}

# Sample users database (in production, use a real database with password hashing)
users_db = {
    "admin@example.com": {
        "id": 1,
        "name": "Admin",
        "password": "hashed_password_here",  # In production, use bcrypt or similar
        "role": "admin"
    },
    "user@example.com": {
        "id": 2,
        "name": "Regular User",
        "password": "hashed_password_here",
        "role": "user"
    }
}

bookings_db = []
admin_notifications = []

# Helper functions
def calculate_booking_days(start_date, end_date):
    try:
        start = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.datetime.strptime(end_date, '%Y-%m-%d')
        if start > end:
            raise ValueError("End date must be after start date")
        return (end - start).days + 1
    except ValueError as e:
        raise ValueError(f"Invalid date: {str(e)}")

# Authentication decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized - Please login"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return jsonify({"error": "Forbidden - Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def home():
    return jsonify({
        "status": "success",
        "message": "Construction Equipment Rental API",
        "environment": app.config['ENVIRONMENT'],
        "endpoints": {
            "equipment": "/api/equipment",
            "calculate_price": "/api/calculate-price",
            "create_payment": "/api/create-payment-intent",
            "bookings": "/api/bookings",
            "login": "/api/login"
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        user = users_db.get(email)
        if not user or user['password'] != password:  # In production, use bcrypt.check_password_hash()
            return jsonify({"error": "Invalid credentials"}), 401

        # Set session data
        session['user_id'] = user['id']
        session['email'] = email
        session['role'] = user['role']
        session['name'] = user['name']

        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user['id'],
                "name": user['name'],
                "email": email,
                "role": user['role']
            }
        })
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})

@app.route('/api/equipment', methods=['GET'])
def get_equipment():
    return jsonify({
        "status": "success",
        "equipment": equipment_db
    })

@app.route('/api/calculate-price', methods=['POST'])
def calculate_price():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        equipment_id = data.get('equipment_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not all([equipment_id, start_date, end_date]):
            return jsonify({"error": "Missing required fields"}), 400
        
        equipment = equipment_db.get(equipment_id)
        if not equipment:
            return jsonify({"error": "Equipment not found"}), 404
            
        days = calculate_booking_days(start_date, end_date)
        total_price = equipment['price_per_day'] * days
        
        return jsonify({
            "status": "success",
            "price": total_price,
            "days": days,
            "equipment_name": equipment['name']
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Price calculation error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/create-payment-intent', methods=['POST'])
@login_required
def create_payment_intent():
    try:
        data = request.get_json()
        amount = data.get('amount')
        equipment_id = data.get('equipment_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not all([amount, equipment_id, start_date, end_date]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Convert amount to cents and validate
        amount_cents = int(float(amount) * 100)
        if amount_cents < 50:  # Minimum charge amount
            return jsonify({"error": "Amount too small"}), 400

        # Verify equipment exists
        if equipment_id not in equipment_db:
            return jsonify({"error": "Equipment not found"}), 404

        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            metadata={
                'user_id': session['user_id'],
                'equipment_id': equipment_id,
                'start_date': start_date,
                'end_date': end_date,
                'user_email': session.get('email', '')
            },
            description=f"Equipment rental: {equipment_db[equipment_id]['name']}"
        )
        
        return jsonify({
            "status": "success",
            "clientSecret": intent.client_secret,
            "paymentIntentId": intent.id,
            "publicKey": app.config['STRIPE_PUBLIC_KEY']
        })
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Payment intent error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/confirm-booking', methods=['POST'])
@login_required
def confirm_booking():
    try:
        data = request.get_json()
        payment_intent_id = data.get('payment_intent_id')
        
        if not payment_intent_id:
            return jsonify({"error": "Payment intent ID required"}), 400

        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        
        if intent.status != 'succeeded':
            return jsonify({"error": "Payment not completed"}), 400
        
        # Verify the payment belongs to the current user
        if str(intent.metadata.get('user_id')) != str(session['user_id']):
            return jsonify({"error": "Payment does not belong to user"}), 403

        # Create booking
        booking = {
            "id": len(bookings_db) + 1,
            "user_id": session['user_id'],
            "user_email": session.get('email', ''),
            "equipment_id": intent.metadata['equipment_id'],
            "equipment_name": equipment_db.get(intent.metadata['equipment_id'], {}).get('name', 'Unknown'),
            "start_date": intent.metadata['start_date'],
            "end_date": intent.metadata['end_date'],
            "amount": intent.amount / 100,
            "payment_intent_id": payment_intent_id,
            "status": "confirmed",
            "created_at": datetime.datetime.now().isoformat()
        }
        
        bookings_db.append(booking)
        
        # Notify admin
        admin_notifications.append({
            "type": "new_booking",
            "booking_id": booking['id'],
            "user_email": booking['user_email'],
            "equipment": booking['equipment_name'],
            "amount": booking['amount'],
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        return jsonify({
            "status": "success",
            "message": "Booking confirmed",
            "booking": booking
        })
    except stripe.error.StripeError as e:
        logger.error(f"Stripe booking error: {str(e)}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Booking confirmation error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/bookings', methods=['GET'])
@login_required
def get_user_bookings():
    user_bookings = [b for b in bookings_db if b['user_id'] == session['user_id']]
    return jsonify({
        "status": "success",
        "bookings": user_bookings
    })

@app.route('/api/admin/bookings', methods=['GET'])
@admin_required
def get_all_bookings():
    return jsonify({
        "status": "success",
        "bookings": bookings_db
    })

@app.route('/api/admin/notifications', methods=['GET'])
@admin_required
def get_admin_notifications():
    return jsonify({
        "status": "success",
        "notifications": admin_notifications
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Server error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=(app.config['ENVIRONMENT'] == 'development'))
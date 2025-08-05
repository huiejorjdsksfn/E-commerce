import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import stripe
import datetime
from functools import wraps
import secrets
from werkzeug.middleware.proxy_fix import ProxyFix

# Initialize Flask app
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configuration
app.config.update({
    'SECRET_KEY': os.getenv('FLASK_SECRET_KEY', 'sample_secret_key_123'),
    'STRIPE_SECRET_KEY': os.getenv('STRIPE_SECRET_KEY', 'sk_test_4eC39HqLyjWDarjtT1zdp7dc'),
    'STRIPE_PUBLIC_KEY': os.getenv('STRIPE_PUBLIC_KEY', 'pk_test_TYooMQauvdEDq54NiTphI7jx'),
    'ENVIRONMENT': os.getenv('ENVIRONMENT', 'development'),
    'API_VERSION': '1.0.0'
})

# Configure CORS
CORS(app, 
     resources={
         r"/api/*": {
             "origins": os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(','),
             "methods": ["GET", "POST", "OPTIONS"],
             "allow_headers": ["Content-Type", "Authorization"]
         }
     },
     supports_credentials=True)

# Configure logging
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/server.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Server startup')

# Mock Stripe for development
if app.config['ENVIRONMENT'] == 'development':
    class MockStripe:
        payment_intents = {}
        
        class PaymentIntent:
            @staticmethod
            def create(amount, currency, metadata=None, **kwargs):
                pi_id = f"pi_mock_{secrets.token_hex(8)}"
                intent = {
                    'id': pi_id,
                    'client_secret': f"mock_client_secret_{secrets.token_hex(8)}",
                    'amount': amount,
                    'currency': currency,
                    'metadata': metadata or {},
                    'status': 'succeeded'
                }
                MockStripe.payment_intents[pi_id] = intent
                return intent
            
            @staticmethod
            def retrieve(pi_id):
                return MockStripe.payment_intents.get(pi_id, {
                    'id': pi_id,
                    'status': 'succeeded',
                    'amount': 10000,
                    'metadata': {
                        'user_id': '1',
                        'equipment_id': 'excavator',
                        'start_date': (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                        'end_date': (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
                    }
                })
    
    stripe = MockStripe()
else:
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
    stripe.api_version = '2023-08-16'

# Sample Database
class Database:
    equipment = {
        "excavator": {"id": "excavator", "name": "Excavator", "price_per_day": 5000, "available": True},
        "bulldozer": {"id": "bulldozer", "name": "Bulldozer", "price_per_day": 4500, "available": True},
        "crane": {"id": "crane", "name": "Crane", "price_per_day": 6000, "available": True}
    }
    
    users = {
        "admin@example.com": {
            "id": 1,
            "name": "Admin",
            "password": "admin123",
            "role": "admin",
            "stripe_customer_id": "cus_mock_admin"
        },
        "user@example.com": {
            "id": 2,
            "name": "John Doe",
            "password": "user123",
            "role": "user",
            "stripe_customer_id": "cus_mock_user"
        }
    }
    
    bookings = []
    admin_notifications = []

db = Database()

# Helper Functions
def calculate_booking_days(start_date, end_date):
    try:
        start = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
        if start > end:
            raise ValueError("End date must be after start date")
        return (end - start).days + 1
    except ValueError as e:
        raise ValueError(f"Invalid date: {str(e)}")

# Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            app.logger.warning(f"Unauthorized access attempt to {request.path}")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            app.logger.warning(f"Admin access required for {request.path}")
            return jsonify({"error": "Forbidden"}), 403
        return f(*args, **kwargs)
    return decorated_function

# API Documentation
@app.route('/')
def api_docs():
    """Main API documentation endpoint"""
    base_url = request.url_root.rstrip('/')
    return jsonify({
        "api": "Construction Equipment Rental API",
        "version": app.config['API_VERSION'],
        "environment": app.config['ENVIRONMENT'],
        "endpoints": {
            "authentication": {
                "login": f"{base_url}/api/login (POST)",
                "logout": f"{base_url}/api/logout (POST)"
            },
            "equipment": {
                "list": f"{base_url}/api/equipment (GET)",
                "calculate_price": f"{base_url}/api/calculate-price (POST)"
            },
            "bookings": {
                "create": f"{base_url}/api/create-payment-intent (POST)",
                "list_user": f"{base_url}/api/bookings (GET)",
                "list_admin": f"{base_url}/api/admin/bookings (GET)"
            },
            "system": {
                "health": f"{base_url}/health (GET)",
                "config": f"{base_url}/config (GET)"
            }
        },
        "sample_credentials": {
            "admin": {"email": "admin@example.com", "password": "admin123"},
            "user": {"email": "user@example.com", "password": "user123"}
        }
    })

# Health Check
@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "database": "connected" if db else "disconnected"
    })

# Config Endpoint
@app.route('/config')
def show_config():
    return jsonify({
        "environment": app.config['ENVIRONMENT'],
        "api_version": app.config['API_VERSION'],
        "debug": app.debug,
        "stripe_configured": bool(app.config['STRIPE_SECRET_KEY'])
    })

# Authentication Routes
@app.route('/api/login', methods=['POST'])
def login():
    """Authenticate user and create session"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        user = db.users.get(email)
        if not user or user['password'] != password:
            app.logger.warning(f"Failed login attempt for email: {email}")
            return jsonify({"error": "Invalid credentials"}), 401

        session.clear()
        session['user_id'] = user['id']
        session['email'] = email
        session['role'] = user['role']
        session['name'] = user['name']

        app.logger.info(f"User {user['id']} logged in successfully")
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
        app.logger.error(f"Login error: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """Clear user session"""
    session.clear()
    return jsonify({"message": "Logged out successfully"})

# Equipment Routes
@app.route('/api/equipment', methods=['GET'])
def list_equipment():
    """List all available equipment"""
    try:
        return jsonify({
            "status": "success",
            "count": len(db.equipment),
            "equipment": list(db.equipment.values())
        })
    except Exception as e:
        app.logger.error(f"Equipment list error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/calculate-price', methods=['POST'])
def calculate_rental_price():
    """Calculate rental price for equipment"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        equipment_id = data.get('equipment_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not all([equipment_id, start_date, end_date]):
            return jsonify({"error": "Missing required fields"}), 400
        
        equipment = db.equipment.get(equipment_id)
        if not equipment:
            return jsonify({"error": "Equipment not found"}), 404
            
        days = calculate_booking_days(start_date, end_date)
        total_price = equipment['price_per_day'] * days
        
        return jsonify({
            "status": "success",
            "equipment": equipment['name'],
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "total_price": total_price,
            "currency": "USD"
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Price calculation error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Booking Routes
@app.route('/api/create-payment-intent', methods=['POST'])
@login_required
def create_payment_intent():
    """Create a payment intent for booking"""
    try:
        data = request.get_json()
        equipment_id = data.get('equipment_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not all([equipment_id, start_date, end_date]):
            return jsonify({"error": "Missing required fields"}), 400

        equipment = db.equipment.get(equipment_id)
        if not equipment:
            return jsonify({"error": "Equipment not found"}), 404

        days = calculate_booking_days(start_date, end_date)
        amount = equipment['price_per_day'] * days
        
        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to cents
            currency='usd',
            customer=db.users.get(session['email'], {}).get('stripe_customer_id'),
            metadata={
                'user_id': session['user_id'],
                'user_email': session['email'],
                'equipment_id': equipment_id,
                'start_date': start_date,
                'end_date': end_date,
                'days': str(days)
            },
            description=f"Rental: {equipment['name']} ({days} days)"
        )
        
        app.logger.info(f"Created payment intent {intent['id']} for user {session['user_id']}")
        return jsonify({
            "status": "success",
            "client_secret": intent['client_secret'],
            "payment_intent_id": intent['id'],
            "amount": amount,
            "currency": "USD",
            "stripe_public_key": app.config['STRIPE_PUBLIC_KEY']
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Payment intent error: {str(e)}")
        return jsonify({"error": "Payment processing failed"}), 500

@app.route('/api/bookings', methods=['GET'])
@login_required
def get_user_bookings():
    """Get bookings for current user"""
    try:
        user_bookings = [b for b in db.bookings if b['user_id'] == session['user_id']]
        return jsonify({
            "status": "success",
            "count": len(user_bookings),
            "bookings": user_bookings
        })
    except Exception as e:
        app.logger.error(f"Bookings error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Admin Routes
@app.route('/api/admin/bookings', methods=['GET'])
@admin_required
def get_all_bookings():
    """Get all bookings (admin only)"""
    try:
        return jsonify({
            "status": "success",
            "count": len(db.bookings),
            "bookings": db.bookings
        })
    except Exception as e:
        app.logger.error(f"Admin bookings error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Error Handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Server error: {str(error)}", exc_info=True)
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=(app.config['ENVIRONMENT'] == 'development'),
        threaded=True
    )
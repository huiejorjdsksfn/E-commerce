require('dotenv').config();
const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

// Initialize Express app
const app = express();

// Middleware
app.use(cors({
  origin: process.env.ALLOWED_ORIGINS || '*',
  credentials: true
}));
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));
app.use('/uploads', express.static('uploads'));

// Configuration
const PORT = process.env.PORT || 5000;
const JWT_SECRET = process.env.JWT_SECRET || 'your_jwt_secret_key';
const ADMIN_DOMAIN = '@e-biz.co.ke';

// Database (in-memory for demo, replace with MongoDB/MySQL in production)
let users = [];
let products = [];
let transactions = [];

// File upload configuration
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, 'uploads/');
  },
  filename: (req, file, cb) => {
    cb(null, Date.now() + path.extname(file.originalname));
  }
});

const upload = multer({ 
  storage: storage,
  limits: { fileSize: 5 * 1024 * 1024 }, // 5MB
  fileFilter: (req, file, cb) => {
    const filetypes = /jpeg|jpg|png|gif/;
    const extname = filetypes.test(path.extname(file.originalname).toLowerCase());
    const mimetype = filetypes.test(file.mimetype);
    
    if (mimetype && extname) {
      return cb(null, true);
    } else {
      cb('Error: Images only!');
    }
  }
}).single('image');

// Helper functions
const generateId = () => Math.random().toString(36).substr(2, 9);
const isAdminEmail = (email) => email.endsWith(ADMIN_DOMAIN);

// Authentication middleware
const authenticate = (req, res, next) => {
  const token = req.headers.authorization?.split(' ')[1];
  if (!token) return res.status(401).json({ message: 'No token provided' });

  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = users.find(u => u.id === decoded.id);
    next();
  } catch (error) {
    res.status(401).json({ message: 'Invalid token' });
  }
};

const authorizeAdmin = (req, res, next) => {
  if (req.user?.role !== 'admin') {
    return res.status(403).json({ message: 'Admin access required' });
  }
  next();
};

// Routes

// Auth Routes
app.post('/api/auth/register', async (req, res) => {
  try {
    const { firstName, lastName, email, phone, businessName, location, password } = req.body;

    // Validation
    if (!email || !password || !firstName || !lastName || !phone || !location) {
      return res.status(400).json({ message: 'All fields are required' });
    }

    if (users.some(u => u.email === email)) {
      return res.status(400).json({ message: 'Email already exists' });
    }

    if (password.length < 8) {
      return res.status(400).json({ message: 'Password must be at least 8 characters' });
    }

    // Hash password
    const hashedPassword = await bcrypt.hash(password, 10);

    // Create user
    const user = {
      id: generateId(),
      name: `${firstName} ${lastName}`,
      email,
      phone,
      businessName,
      location,
      password: hashedPassword,
      role: isAdminEmail(email) ? 'admin' : 'user',
      status: 'active',
      createdAt: new Date().toISOString()
    };

    users.push(user);

    // Generate token
    const token = jwt.sign({ id: user.id, email: user.email, role: user.role }, JWT_SECRET, { expiresIn: '7d' });

    res.status(201).json({ 
      user: { 
        id: user.id,
        name: user.name,
        email: user.email,
        phone: user.phone,
        businessName: user.businessName,
        location: user.location,
        role: user.role,
        status: user.status
      },
      token 
    });
  } catch (error) {
    console.error('Registration error:', error);
    res.status(500).json({ message: 'Server error during registration' });
  }
});

app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    // Find user
    const user = users.find(u => u.email === email);
    if (!user) {
      return res.status(401).json({ message: 'Invalid credentials' });
    }

    // Check password
    const isMatch = await bcrypt.compare(password, user.password);
    if (!isMatch) {
      return res.status(401).json({ message: 'Invalid credentials' });
    }

    // Generate token
    const token = jwt.sign({ id: user.id, email: user.email, role: user.role }, JWT_SECRET, { expiresIn: '7d' });

    res.json({ 
      user: { 
        id: user.id,
        name: user.name,
        email: user.email,
        phone: user.phone,
        businessName: user.businessName,
        location: user.location,
        role: user.role,
        status: user.status
      },
      token 
    });
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ message: 'Server error during login' });
  }
});

app.get('/api/auth/verify', authenticate, (req, res) => {
  res.json({ 
    user: { 
      id: req.user.id,
      name: req.user.name,
      email: req.user.email,
      phone: req.user.phone,
      businessName: req.user.businessName,
      location: req.user.location,
      role: req.user.role,
      status: req.user.status
    }
  });
});

// Product Routes
app.get('/api/products', authenticate, (req, res) => {
  // Filter products by user location if not admin
  let filteredProducts = products;
  if (req.user.role !== 'admin') {
    filteredProducts = products.filter(p => p.location === req.user.location);
  }
  res.json(filteredProducts);
});

app.post('/api/products', authenticate, (req, res) => {
  upload(req, res, async (err) => {
    if (err) {
      return res.status(400).json({ message: err });
    }

    try {
      const { name, description, category, price, stock, location } = req.body;

      // Validation
      if (!name || !category || !price || !stock || !location) {
        return res.status(400).json({ message: 'Required fields missing' });
      }

      const product = {
        id: generateId(),
        name,
        description,
        category,
        price: parseFloat(price),
        stock: parseInt(stock),
        location,
        image: req.file ? `/uploads/${req.file.filename}` : null,
        createdAt: new Date().toISOString(),
        createdBy: req.user.id
      };

      products.push(product);
      res.status(201).json(product);
    } catch (error) {
      console.error('Product creation error:', error);
      res.status(500).json({ message: 'Server error creating product' });
    }
  });
});

app.put('/api/products/:id', authenticate, (req, res) => {
  upload(req, res, async (err) => {
    if (err) {
      return res.status(400).json({ message: err });
    }

    try {
      const { id } = req.params;
      const { name, description, category, price, stock, location } = req.body;

      const productIndex = products.findIndex(p => p.id === id);
      if (productIndex === -1) {
        return res.status(404).json({ message: 'Product not found' });
      }

      // Update product
      products[productIndex] = {
        ...products[productIndex],
        name,
        description,
        category,
        price: parseFloat(price),
        stock: parseInt(stock),
        location,
        image: req.file ? `/uploads/${req.file.filename}` : products[productIndex].image,
        updatedAt: new Date().toISOString()
      };

      res.json(products[productIndex]);
    } catch (error) {
      console.error('Product update error:', error);
      res.status(500).json({ message: 'Server error updating product' });
    }
  });
});

app.delete('/api/products/:id', authenticate, authorizeAdmin, (req, res) => {
  try {
    const { id } = req.params;
    const productIndex = products.findIndex(p => p.id === id);
    
    if (productIndex === -1) {
      return res.status(404).json({ message: 'Product not found' });
    }

    // Remove product image if exists
    if (products[productIndex].image) {
      const imagePath = path.join(__dirname, products[productIndex].image);
      if (fs.existsSync(imagePath)) {
        fs.unlinkSync(imagePath);
      }
    }

    products.splice(productIndex, 1);
    res.json({ message: 'Product deleted successfully' });
  } catch (error) {
    console.error('Product deletion error:', error);
    res.status(500).json({ message: 'Server error deleting product' });
  }
});

// Transaction Routes
app.get('/api/transactions', authenticate, (req, res) => {
  // Filter transactions by user location if not admin
  let filteredTransactions = transactions;
  if (req.user.role !== 'admin') {
    filteredTransactions = transactions.filter(t => t.location === req.user.location);
  }
  res.json(filteredTransactions);
});

app.post('/api/transactions', authenticate, async (req, res) => {
  try {
    const { items, customer, paymentMethod, amountReceived } = req.body;

    // Validation
    if (!items || !Array.isArray(items) || items.length === 0) {
      return res.status(400).json({ message: 'Transaction must contain items' });
    }

    // Calculate totals
    const subtotal = items.reduce((sum, item) => sum + (item.price * item.quantity), 0);
    const tax = subtotal * 0.16; // 16% VAT
    const total = subtotal + tax;

    // Update product stock
    items.forEach(item => {
      const product = products.find(p => p.id === item.productId);
      if (product) {
        product.stock -= item.quantity;
      }
    });

    // Create transaction
    const transaction = {
      id: `TXN-${Date.now()}`,
      date: new Date().toISOString(),
      items,
      subtotal,
      tax,
      total,
      paymentMethod,
      amountReceived: paymentMethod === 'cash' ? parseFloat(amountReceived) : null,
      change: paymentMethod === 'cash' ? parseFloat(amountReceived) - total : null,
      customer: customer || null,
      status: paymentMethod === 'mpesa' ? 'pending' : 'completed',
      location: req.user.location,
      processedBy: req.user.id
    };

    transactions.unshift(transaction);

    // Simulate M-Pesa payment completion
    if (paymentMethod === 'mpesa') {
      setTimeout(() => {
        transaction.status = 'completed';
        transaction.mpesaCode = `MP${Date.now().toString().slice(-6)}`;
      }, 3000);
    }

    res.status(201).json(transaction);
  } catch (error) {
    console.error('Transaction error:', error);
    res.status(500).json({ message: 'Server error processing transaction' });
  }
});

// Payment Routes
app.post('/api/payments/create-payment-intent', authenticate, async (req, res) => {
  try {
    const { amount } = req.body;
    
    const paymentIntent = await stripe.paymentIntents.create({
      amount: Math.round(amount * 100), // Convert to cents
      currency: 'kes',
      metadata: {
        userId: req.user.id,
        location: req.user.location
      }
    });

    res.json({ clientSecret: paymentIntent.client_secret });
  } catch (error) {
    console.error('Payment intent error:', error);
    res.status(500).json({ message: 'Server error creating payment intent' });
  }
});

// User Routes (Admin only)
app.get('/api/users', authenticate, authorizeAdmin, (req, res) => {
  res.json(users);
});

app.post('/api/users', authenticate, authorizeAdmin, async (req, res) => {
  try {
    const { email, role, password } = req.body;

    // Validation
    if (!email || !role || !password) {
      return res.status(400).json({ message: 'All fields are required' });
    }

    if (users.some(u => u.email === email)) {
      return res.status(400).json({ message: 'Email already exists' });
    }

    // Hash password
    const hashedPassword = await bcrypt.hash(password, 10);

    // Create user
    const user = {
      id: generateId(),
      name: email.split('@')[0],
      email,
      password: hashedPassword,
      role,
      status: 'active',
      createdAt: new Date().toISOString()
    };

    users.push(user);

    res.status(201).json({ 
      id: user.id,
      name: user.name,
      email: user.email,
      role: user.role,
      status: user.status
    });
  } catch (error) {
    console.error('User creation error:', error);
    res.status(500).json({ message: 'Server error creating user' });
  }
});

// Profile Routes
app.put('/api/profile', authenticate, async (req, res) => {
  try {
    const { name, phone, businessName, location } = req.body;

    const userIndex = users.findIndex(u => u.id === req.user.id);
    if (userIndex === -1) {
      return res.status(404).json({ message: 'User not found' });
    }

    // Update user
    users[userIndex] = {
      ...users[userIndex],
      name,
      phone,
      businessName,
      location,
      updatedAt: new Date().toISOString()
    };

    res.json({ 
      id: users[userIndex].id,
      name: users[userIndex].name,
      email: users[userIndex].email,
      phone: users[userIndex].phone,
      businessName: users[userIndex].businessName,
      location: users[userIndex].location,
      role: users[userIndex].role,
      status: users[userIndex].status
    });
  } catch (error) {
    console.error('Profile update error:', error);
    res.status(500).json({ message: 'Server error updating profile' });
  }
});

app.put('/api/profile/password', authenticate, async (req, res) => {
  try {
    const { currentPassword, newPassword } = req.body;

    const user = users.find(u => u.id === req.user.id);
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }

    // Verify current password
    const isMatch = await bcrypt.compare(currentPassword, user.password);
    if (!isMatch) {
      return res.status(400).json({ message: 'Current password is incorrect' });
    }

    // Hash new password
    const hashedPassword = await bcrypt.hash(newPassword, 10);
    user.password = hashedPassword;
    user.updatedAt = new Date().toISOString();

    res.json({ message: 'Password updated successfully' });
  } catch (error) {
    console.error('Password update error:', error);
    res.status(500).json({ message: 'Server error updating password' });
  }
});

// Initialize with sample data if in development
if (process.env.ENVIRONMENT === 'development') {
  // Sample products
  products = [
    {
      id: 'P001',
      name: 'Fresh Avocados',
      description: 'Freshly harvested avocados from Embu',
      category: 'Produce',
      price: 50,
      stock: 120,
      location: 'Embu Town',
      image: 'https://images.unsplash.com/photo-1601493700631-2b16ec4b4716',
      createdAt: new Date().toISOString(),
      createdBy: 'system'
    },
    {
      id: 'P002',
      name: 'Organic Honey',
      description: 'Pure honey from Embu beekeepers',
      category: 'Food',
      price: 800,
      stock: 25,
      location: 'Runyenjes',
      image: 'https://images.unsplash.com/photo-1587049352851-8d4e89133924',
      createdAt: new Date().toISOString(),
      createdBy: 'system'
    }
  ];

  // Sample users
  users = [
    {
      id: 'U001',
      name: 'Admin User',
      email: 'admin@e-biz.co.ke',
      phone: '254700000001',
      businessName: 'EmbuBiz',
      location: 'Embu Town',
      password: bcrypt.hashSync('admin123', 10),
      role: 'admin',
      status: 'active',
      createdAt: new Date().toISOString()
    },
    {
      id: 'U002',
      name: 'Regular User',
      email: 'user@example.com',
      phone: '254700000002',
      businessName: 'Local Shop',
      location: 'Runyenjes',
      password: bcrypt.hashSync('user123', 10),
      role: 'user',
      status: 'active',
      createdAt: new Date().toISOString()
    }
  ];

  // Sample transactions
  transactions = [
    {
      id: 'TXN-001',
      date: new Date(Date.now() - 86400000).toISOString(),
      items: [
        { productId: 'P001', name: 'Fresh Avocados', price: 50, quantity: 5 },
        { productId: 'P002', name: 'Organic Honey', price: 800, quantity: 1 }
      ],
      subtotal: 1050,
      tax: 168,
      total: 1218,
      paymentMethod: 'mpesa',
      mpesaPhone: '254712345678',
      mpesaCode: 'MP123456',
      customer: { id: 'C001', name: 'John Mwangi', phone: '254712345678' },
      status: 'completed',
      location: 'Embu Town',
      processedBy: 'U001'
    }
  ];
}

// Start server
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  console.log(`Environment: ${process.env.ENVIRONMENT || 'production'}`);
  console.log(`Admin domain: ${ADMIN_DOMAIN}`);
  console.log(`Allowed origins: ${process.env.ALLOWED_ORIGINS || '*'}`);
});
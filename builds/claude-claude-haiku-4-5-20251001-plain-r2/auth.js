const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');

const SECRET = 'noteshare-secret-key-change-in-production';

const auth = {
  hashPassword: async (password) => {
    return bcrypt.hash(password, 10);
  },

  comparePassword: async (password, hash) => {
    return bcrypt.compare(password, hash);
  },

  createToken: (userId) => {
    return jwt.sign({ userId }, SECRET, { expiresIn: '30d' });
  },

  verifyToken: (token) => {
    try {
      return jwt.verify(token, SECRET);
    } catch (err) {
      return null;
    }
  },

  generateShareToken: () => {
    return Math.random().toString(36).substr(2, 20);
  }
};

module.exports = auth;

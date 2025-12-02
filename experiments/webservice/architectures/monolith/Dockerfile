FROM node:18-alpine

WORKDIR /app

# Copy package.json first for better Docker layer caching
COPY package*.json ./

# Install dependencies
RUN npm install --production

# Copy all application code
COPY index.js ./
COPY functions/ ./functions/
COPY auth/ ./auth/

# Copy data directories (used by functions)
COPY productcatalog/ ./productcatalog/
COPY currency/ ./currency/

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"

# Start the server
CMD ["node", "index.js"]
FROM node:18-alpine

WORKDIR /app

# Copy all shared code
COPY functions/ ./functions/
COPY auth/ ./auth/
COPY productcatalog/ ./productcatalog/
COPY currency/ ./currency/
COPY microservices/ ./microservices/
# Copy auth again to microservices/auth (after microservices copy so it doesn't get overwritten)
COPY auth/ ./microservices/auth/

# Copy monolith-specific files
COPY monolith/package*.json ./
COPY monolith/server.js ./

# Install dependencies (both for monolith and microservices)
RUN npm install --production

# Install microservice dependencies
RUN cd microservices/product-service && npm install --production
RUN cd microservices/cart-service && npm install --production
RUN cd microservices/order-service && npm install --production
RUN cd microservices/content-service && npm install --production
RUN cd microservices/frontend-service && npm install --production

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"

# Start the server
CMD ["node", "index.js"]

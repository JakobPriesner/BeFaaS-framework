"""
Constants and configuration for BeFaaS plotting.
"""

# Warmup period to exclude from pure performance plots (in seconds)
# This helps eliminate cold start effects from performance metrics
WARMUP_SECONDS = 60

# Define endpoint categories for grouping (functional categories only)
ENDPOINT_CATEGORIES = {
    'User Management': ['register', 'setUser', 'login', 'logout'],
    'Product Browsing': ['frontend', 'EASYSTOOL', 'QWERTY', 'REFLECTXXX', 'product'],
    'Shopping Cart': ['addCartItem', 'cart', 'removeCartItem', 'updateCart'],
    'Checkout': ['checkout', 'payment', 'order']
}

# Category colors for consistent visualization
CATEGORY_COLORS = {
    'User Management': '#3498db',
    'Product Browsing': '#2ecc71',
    'Shopping Cart': '#f39c12',
    'Checkout': '#e74c3c',
    'Authentication': '#9b59b6',
    'Other': '#95a5a6'
}

# AWS Lambda Pricing (us-east-1, as of 2024)
AWS_LAMBDA_PRICING = {
    'request_cost': 0.20 / 1_000_000,  # $0.20 per 1M requests
    'duration_cost_per_gb_second': 0.0000166667,  # Per GB-second
}

# AWS API Gateway Pricing
AWS_API_GATEWAY_PRICING = {
    'rest_api_per_million': 3.50,
    'http_api_per_million': 1.00,
}

# GCP Cloud Functions Pricing
GCP_CLOUD_FUNCTIONS_PRICING = {
    'invocations_per_million': 0.40,
    'compute_per_100ms_128mb': 0.000000231,
}

# Azure Functions Pricing
AZURE_FUNCTIONS_PRICING = {
    'executions_per_million': 0.20,
    'gb_seconds': 0.000016,
}

# Define the static function call graph based on source code analysis
FUNCTION_CALL_GRAPH = {
    'frontend': ['supportedcurrencies', 'listproducts', 'getads', 'currency', 'getproduct',
                 'listrecommendations', 'getcart', 'shipmentquote', 'checkout', 'login',
                 'register', 'emptycart', 'addcartitem'],
    'checkout': ['getcart', 'getproduct', 'currency', 'shipmentquote', 'payment',
                 'shiporder', 'email', 'emptycart'],
    'getcart': ['cartkvstorage'],
    'addcartitem': ['cartkvstorage'],
    'emptycart': ['cartkvstorage'],
    'listrecommendations': ['listproducts'],
    # Leaf functions (no outgoing calls)
    'listproducts': [],
    'getproduct': [],
    'supportedcurrencies': [],
    'currency': [],
    'shipmentquote': [],
    'payment': [],
    'shiporder': [],
    'email': [],
    'getads': [],
    'login': [],
    'register': [],
    'cartkvstorage': [],
    'searchproducts': [],
}

# Functions that require authentication (have verifyJWT)
AUTH_REQUIRED_FUNCTIONS = {
    'checkout', 'getcart', 'addcartitem', 'emptycart', 'payment', 'cartkvstorage'
}

# Function categories for visualization
FUNCTION_CATEGORIES = {
    'entry': {'frontend'},
    'critical': {'checkout', 'payment', 'shiporder', 'email'},
    'cart': {'getcart', 'addcartitem', 'emptycart', 'cartkvstorage'},
    'product': {'listproducts', 'getproduct', 'searchproducts', 'listrecommendations'},
    'utility': {'supportedcurrencies', 'currency', 'shipmentquote', 'getads'},
    'auth': {'login', 'register'},
}
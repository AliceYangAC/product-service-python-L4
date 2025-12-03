from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from dotenv import load_dotenv
import os
from pymongo import MongoClient
from azure.storage.blob import BlobServiceClient

load_dotenv()

app = Flask(__name__)

CORS(app)

# MongoDB connection 
mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
client = MongoClient(mongo_uri)
db = client.productdb
collection = db.products

# Seed initial data if collection is empty
def seed_data():
    if collection.count_documents({}) == 0:
        # Generated products with AI with images hosted in Azure Blob Storage
        # store-front hits product-service's endpoint @ port 3002 to get the products
        # located at the provided image path in Blob Storage
        [
            {
                "id": 1,
                "name": "UltraSlim X1 Laptop",
                "price": 1299.99,
                "description": "Experience peak performance with the UltraSlim X1. Featuring a 4K InfinityEdge display, i9 processor, and all-day battery life for professionals on the go.",
                "image": "/images/laptop_x1.jpg",
                "category": "Computers & Tablets",
                "brand": "Apex"
            },
            {
                "id": 2,
                "name": "NoiseGuard Pro Headphones",
                "price": 349.99,
                "description": "Immerse yourself in music with industry-leading noise cancellation. The NoiseGuard Pro offers 30 hours of listening time and plush ear cushions for comfort.",
                "image": "/images/headphones_pro.jpg",
                "category": "Audio",
                "brand": "Aura"
            },
            {
                "id": 3,
                "name": "Visionary 4K Monitor",
                "price": 499.99,
                "description": "See every detail with the Visionary 27-inch 4K monitor. Perfect for designers and gamers, featuring HDR support and a 144Hz refresh rate.",
                "image": "/images/monitor_4k.jpg",
                "category": "Computer Accessories",
                "brand": "OptiMax"
            },
            {
                "id": 4,
                "name": "GamerZ Console 5",
                "price": 499.99,
                "description": "Next-gen gaming is here. Play games in stunning 4K at 120fps with ray tracing technology and ultra-fast load times.",
                "image": "/images/console_5.jpg",
                "category": "Video Games",
                "brand": "Nexus"
            },
            {
                "id": 5,
                "name": "SmartWatch Series 7",
                "price": 399.99,
                "description": "Track your fitness, monitor your health, and stay connected without your phone. Features an always-on Retina display and crack-resistant crystal.",
                "image": "/images/smartwatch_7.jpg",
                "category": "Wearable Technology",
                "brand": "Vital"
            },
            {
                "id": 6,
                "name": "BlueBeat Portable Speaker",
                "price": 129.99,
                "description": "Take the party anywhere with the BlueBeat. Waterproof, dustproof, and drop-proof, delivering powerful 360-degree sound.",
                "image": "/images/speaker_blue.jpg",
                "category": "Audio",
                "brand": "Roam"
            },
            {
                "id": 7,
                "name": "ProTab Air Tablet",
                "price": 599.99,
                "description": "Power and portability combined. The ProTab Air features the M1 chip, a stunning Liquid Retina display, and compatibility with the smart pencil.",
                "image": "/images/tablet_air.jpg",
                "category": "Computers & Tablets",
                "brand": "Forge"
            },
            {
                "id": 8,
                "name": "MechKey RGB Keyboard",
                "price": 149.99,
                "description": "Dominate the competition with the MechKey RGB. Features responsive mechanical switches, customizable macro keys, and vibrant backlighting.",
                "image": "/images/keyboard_rgb.jpg",
                "category": "Computer Accessories",
                "brand": "Zenith"
            },
            {
                "id": 9,
                "name": "CineView 65\" OLED TV",
                "price": 1999.99,
                "description": "Experience true blacks and rich colors with the CineView OLED. Smart TV capabilities built-in with voice control and AI picture enhancement.",
                "image": "/images/tv_oled.jpg",
                "category": "TV & Home Theater",
                "brand": "Luminos"
            },
            {
                "id": 10,
                "name": "Bolt External SSD 1TB",
                "price": 159.99,
                "description": "Transfer files in seconds with the Bolt SSD. Rugged design, USB-C connectivity, and read speeds up to 1050MB/s.",
                "image": "/images/ssd_bolt.jpg",
                "category": "Computer Accessories",
                "brand": "Velocity"
            }
        ]
        collection.insert_many(initial_products)
        print("Database seeded successfully.")

# Run seeding immediately on startup
seed_data()

# Flask routes
# Health check endpoint
@app.route('/health', methods=['GET', 'HEAD'])
def health():
    version = os.getenv("APP_VERSION", "0.1.0")
    return jsonify({"status": "ok", "version": version})

# store-front: gets all products
@app.route('/', methods=['GET'])
def get_products():
    products = list(collection.find({}, {'_id': 0}))
    return jsonify(products)

# store-front: gets a single product by ID
# Note: add the call later to query MongoDB for past orders for the recommendations feature
@app.route('/<int:product_id>', methods=['GET'])
def get_product(product_id):
    product = collection.find_one({"id": product_id}, {'_id': 0})
    if product:
        return jsonify(product)
    else:
        return "Product not found", 404

# store-admin: adds a new product
@app.route('/', methods=['POST'])
def add_product():
    if not request.json:
        return "Invalid input", 400
    # We query the DB for the highest ID to ensure safety
    last_product = collection.find_one(sort=[("id", -1)])
    new_id = (last_product['id'] + 1) if last_product else 1

    new_product = request.json
    new_product['id'] = new_id
    
    collection.insert_one(new_product)
    
    # Return created object (without _id)
    del new_product['_id']
    return jsonify(new_product)

# store-admin: updates an existing product
@app.route('/', methods=['PUT'])
def update_product():
    if not request.json or 'id' not in request.json:
        return "Invalid input", 400
    
    update_data = request.json
    target_id = update_data['id']
    
    result = collection.update_one({"id": target_id}, {"$set": update_data})
    
    if result.matched_count == 0:
        return "Product not found", 404

    # Return the updated product
    updated_product = collection.find_one({"id": target_id}, {'_id': 0})
    return jsonify(updated_product)

# store-admin deletes a product by ID
@app.route('/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    # Returns table without the deleted product
    result = collection.delete_one({"id": product_id})
    
    # If no product was deleted, it means it wasn't found
    if result.deleted_count == 0:
        return "Product not found", 404

    return "", 200

# store-front & store-admin: serves product images from Azure Blob Storage to store-front
@app.route('/images/<filename>')
def get_image(filename):
    try:
        blob_service = BlobServiceClient.from_connection_string(os.getenv("BLOB_CONN_STR"))
        blob_client = blob_service.get_blob_client(container="product-images", blob=filename)
        image_data = blob_client.download_blob().readall()

        # Return the data
        return Response(image_data, mimetype="image/jpeg")

    except Exception as e:
        return "Image not found", 404

if __name__ == '__main__':
    # Maps to: settings.port: 3002
    port = int(os.getenv('PORT', 3002))
    print(f"Listening on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port)
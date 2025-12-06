from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from dotenv import load_dotenv
import os
import mimetypes

# Database Imports
from pymongo import MongoClient
from azure.cosmos import CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

load_dotenv()

app = Flask(__name__)
CORS(app)

# --- REPOSITORY ABSTRACTION ---

class MongoRepository:
    def __init__(self, uri, db_name="productdb", collection_name="products"):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        print(f"Connected to MongoDB: {db_name}")

    def get_all(self):
        return list(self.collection.find({}, {'_id': 0}))

    def get_one(self, pid):
        return self.collection.find_one({"id": pid}, {'_id': 0})

    def add(self, product):
        last_product = self.collection.find_one(sort=[("id", -1)])
        new_id = (last_product['id'] + 1) if last_product else 1
        product['id'] = new_id
        self.collection.insert_one(product)
        del product['_id']
        return product

    def update(self, product):
        target_id = product['id']
        result = self.collection.update_one({"id": target_id}, {"$set": product})
        if result.matched_count == 0: return None
        return self.get_one(target_id)

    def delete(self, pid):
        result = self.collection.delete_one({"id": pid})
        return result.deleted_count > 0

    def count(self):
        return self.collection.count_documents({})
        
    def seed_many(self, products):
        self.collection.insert_many(products)

class CosmosRepository:
    def __init__(self, endpoint, db_name, container_name, pk_field, pk_value):
        # Workload Identity Authentication
        if os.getenv('USE_WORKLOAD_IDENTITY_AUTH') == "true":
            credential = DefaultAzureCredential()
            self.client = CosmosClient(endpoint, credential=credential)
        else:
            raise ValueError("Workload Identity Configuration Required")

        self.pk_field = pk_field   # e.g., "storeId"
        self.pk_value = pk_value   # e.g., "bestbuy"

        # Ensure DB/Container exist
        db = self.client.create_database_if_not_exists(id=db_name)
        self.container = db.create_container_if_not_exists(
            id=container_name, 
            partition_key=PartitionKey(path=f"/{pk_field}")
        )
        print(f"Connected to Cosmos DB SQL: {endpoint} | Partition: {pk_field}={pk_value}")

    # Helper: Convert App Model (int id) to Cosmos Model (str id + partition key)
    def _to_cosmos(self, product):
        p = product.copy()
        p['id'] = str(p['id'])       # System ID must be string
        p['int_id'] = int(product['id']) # Keep int for logic
        p[self.pk_field] = self.pk_value # Inject Partition Key
        return p

    # Helper: Convert Cosmos Model back to App Model
    def _from_cosmos(self, doc):
        d = {k: v for k, v in doc.items() if not k.startswith('_')}
        if 'int_id' in d:
            d['id'] = d['int_id']
            del d['int_id']
        if self.pk_field in d:
            del d[self.pk_field]
        return d

    def get_all(self):
        query = f"SELECT * FROM c WHERE c.{self.pk_field} = @pk"
        items = list(self.container.query_items(
            query=query, parameters=[{"name": "@pk", "value": self.pk_value}],
            enable_cross_partition_query=False
        ))
        return [self._from_cosmos(i) for i in items]

    def get_one(self, pid):
        try:
            item = self.container.read_item(item=str(pid), partition_key=self.pk_value)
            return self._from_cosmos(item)
        except ResourceNotFoundError:
            return None

    def add(self, product):
        # Auto-increment logic using SQL
        query = f"SELECT TOP 1 c.int_id FROM c WHERE c.{self.pk_field} = @pk ORDER BY c.int_id DESC"
        items = list(self.container.query_items(
            query=query, parameters=[{"name": "@pk", "value": self.pk_value}]
        ))
        new_id = (items[0]['int_id'] + 1) if items else 1
        product['id'] = new_id
        
        self.container.create_item(body=self._to_cosmos(product))
        return product

    def update(self, product):
        if not self.get_one(product['id']): return None
        self.container.upsert_item(body=self._to_cosmos(product))
        return product

    def delete(self, pid):
        try:
            self.container.delete_item(item=str(pid), partition_key=self.pk_value)
            return True
        except ResourceNotFoundError: return False

    def count(self):
        query = f"SELECT VALUE COUNT(1) FROM c WHERE c.{self.pk_field} = @pk"
        items = list(self.container.query_items(
            query=query, parameters=[{"name": "@pk", "value": self.pk_value}]
        ))
        return items[0] if items else 0

    def seed_many(self, products):
        for p in products:
            self.container.create_item(body=self._to_cosmos(p))

# --- CONFIGURATION ---
DB_API = os.getenv('PRODUCT_DB_API', 'mongodb')

if DB_API == 'cosmosdbsql':
    # 
    repo = CosmosRepository(
        endpoint=os.getenv('PRODUCT_DB_URI'),
        db_name=os.getenv('PRODUCT_DB_NAME', 'productdb'),
        container_name=os.getenv('PRODUCT_DB_CONTAINER_NAME', 'products'),
        pk_field=os.getenv('PRODUCT_DB_PARTITION_KEY', 'storeId'),
        pk_value=os.getenv('PRODUCT_DB_PARTITION_VALUE', 'default')
    )
else:
    repo = MongoRepository(os.getenv('PRODUCT_DB_URI'))

# Azure Blob Config (Preserved)
BLOB_CONN_STR = os.getenv("BLOB_CONN_STR")
CONTAINER_NAME = "product-images"

# --- SEED DATA ---
def seed_data():
    if repo.count() == 0:
        initial_products = [
            {"id": 1, "name": "UltraSlim X1 Laptop", "price": 1299.99, "description": "Experience peak performance...", "category": "Computers & Tablets", "brand": "Apex"},
            {"id": 2, "name": "NoiseGuard Pro Headphones", "price": 349.99, "description": "Immerse yourself...", "category": "Audio", "brand": "Aura"},
            {"id": 3, "name": "Visionary 4K Monitor", "price": 499.99, "description": "See every detail...", "category": "Computer Accessories", "brand": "OptiMax"},
            {"id": 4, "name": "GamerZ Console 5", "price": 499.99, "description": "Next-gen gaming...", "category": "Video Games", "brand": "Nexus"},
            {"id": 5, "name": "SmartWatch Series 7", "price": 399.99, "description": "Track your fitness...", "category": "Wearable Technology", "brand": "Vital"},
            {"id": 6, "name": "BlueBeat Portable Speaker", "price": 129.99, "description": "Take the party anywhere...", "category": "Audio", "brand": "Roam"},
            {"id": 7, "name": "ProTab Air Tablet", "price": 599.99, "description": "Power and portability...", "category": "Computers & Tablets", "brand": "Forge"},
            {"id": 8, "name": "MechKey RGB Keyboard", "price": 149.99, "description": "Dominate the competition...", "category": "Computer Accessories", "brand": "Zenith"},
            {"id": 9, "name": "CineView 65\" OLED TV", "price": 1999.99, "description": "Experience true blacks...", "category": "TV & Home Theater", "brand": "Luminos"},
            {"id": 10, "name": "Bolt External SSD 1TB", "price": 159.99, "description": "Transfer files in seconds...", "category": "Computer Accessories", "brand": "Velocity"}
        ]
        repo.seed_many(initial_products)
        print("Database seeded successfully.")

seed_data()

# --- ROUTES ---

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "api": DB_API})

@app.route('/', methods=['GET'])
def get_products():
    return jsonify(repo.get_all())

@app.route('/<int:product_id>', methods=['GET'])
def get_product(product_id):
    product = repo.get_one(product_id)
    return jsonify(product) if product else ("Product not found", 404)

@app.route('/', methods=['POST'])
def add_product():
    if not request.json:
        return "Invalid input", 400
    new_product = repo.add(request.json)
    return jsonify(new_product)

@app.route('/', methods=['PUT'])
def update_product():
    if not request.json or 'id' not in request.json:
        return "Invalid input", 400
    updated_product = repo.update(request.json)
    return jsonify(updated_product) if updated_product else ("Product not found", 404)

@app.route('/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    success = repo.delete(product_id)
    return ("", 200) if success else ("Product not found", 404)

# --- IMAGE HANDLING ---
# (Preserved exactly as requested)

@app.route('/upload', methods=['POST'])
def upload_image():
    file = request.files.get('file')
    product_id = request.form.get('productId')

    if not file or not product_id:
        return "File and productId required", 400

    try:
        blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
        container_client = blob_service.get_container_client(CONTAINER_NAME)
        
        if not container_client.exists():
            container_client.create_container()

        old_blobs = container_client.list_blobs(name_starts_with=f"{product_id}.")
        for blob in old_blobs:
            container_client.delete_blob(blob.name)

        ext = os.path.splitext(file.filename)[1].lower()
        if not ext:
            ext = ".jpg" 
            
        filename = f"{product_id}{ext}"
        blob_client = container_client.get_blob_client(filename)
        blob_client.upload_blob(file, overwrite=True)

        return jsonify({"status": "uploaded", "filename": filename})

    except Exception as e:
        print(f"Upload Error: {e}")
        return "Upload failed", 500

@app.route('/<int:product_id>/image', methods=['GET'])
def get_product_image(product_id):
    try:
        blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
        container_client = blob_service.get_container_client(CONTAINER_NAME)

        blobs = list(container_client.list_blobs(name_starts_with=f"{product_id}."))
        
        if not blobs:
            return "Image not found", 404

        # Take the first match
        blob_name = blobs[0].name
        blob_client = container_client.get_blob_client(blob_name)
        
        image_data = blob_client.download_blob().readall()
        
        mime_type, _ = mimetypes.guess_type(blob_name)
        return Response(image_data, mimetype=mime_type or "image/jpeg")

    except Exception:
        return "Image not found", 404

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3002))
    print(f"Listening on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port)
import os
import uuid
import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func as sql_func

# --- CẤU HÌNH ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

# --- CẤU HÌNH DATABASE (Tương thích Render & Local) ---
# Lấy URL từ biến môi trường của Render, nếu không có thì dùng SQLite local
database_url = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'license.db'))

# Sửa lỗi 'postgres://' thành 'postgresql://' cho thư viện SQLAlchemy mới
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- KHÓA BÍ MẬT ADMIN ---
ADMIN_SECRET = "0988001140inoxTruong@1994" 


# --- MÔ HÌNH DATABASE ---
class License(db.Model):
    __tablename__ = 'licenses'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    license_key = db.Column(db.String(100), unique=True, nullable=False) 
    expiry_date = db.Column(db.Date, nullable=False)
    allowed_machine_id = db.Column(db.String(100), default=None)
    status = db.Column(db.String(10), default='ACTIVE')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_check = db.Column(db.DateTime, default=None)
    
    zalo_id = db.Column(db.String(100), default=None)
    activation_note = db.Column(db.String(255), default=None)

    def __repr__(self):
        return f"<License {self.license_key} - Status: {self.status}>"

# --- TẠO BẢNG DỮ LIỆU TỰ ĐỘNG ---
with app.app_context():
    try:
        db.create_all()
        print("✅ Database initialized successfully.")
    except Exception as e:
        print(f"⚠️ Database initialization warning: {e}")

# --- XỬ LÝ LỖI ---
@app.errorhandler(Exception)
def handle_error(error):
    code = 500
    if hasattr(error, 'code'):
        code = error.code
    return jsonify({"status": "ERROR", "message": str(error), "code": code}), code


# --- API ENDPOINTS ---

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "RUNNING", 
        "message": "License Server is Online",
        "time": datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    }), 200

# 1. TẠO KEY MỚI (Dành cho Admin Tool)
@app.route('/api/v1/create', methods=['POST'])
def create_license():
    data = request.json or {}
    
    if data.get('admin_key') != ADMIN_SECRET:
        return jsonify({'status': 'FAIL', 'message': 'Admin key incorrect.'}), 401
    
    license_key = data.get('license_key')
    expiry_date_str = data.get('expiry_date') # YYYY-MM-DD
    zalo_id = data.get('zalo_id')

    if not license_key or not expiry_date_str:
        return jsonify({'status': 'FAIL', 'message': 'Missing data.'}), 400

    if License.query.filter_by(license_key=license_key).first():
        return jsonify({'status': 'FAIL', 'message': 'License key already exists.'}), 409

    try:
        expiry_date = datetime.datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
        new_license = License(
            license_key=license_key,
            expiry_date=expiry_date,
            status='ACTIVE',
            zalo_id=zalo_id
        )
        db.session.add(new_license)
        db.session.commit()
        return jsonify({'status': 'CREATED', 'message': 'License created.'}), 200
    except ValueError:
        return jsonify({'status': 'FAIL', 'message': 'Invalid date format.'}), 400
    except Exception as e:
        return jsonify({'status': 'ERROR', 'message': str(e)}), 500

# 2. KÍCH HOẠT KEY (Client gọi)
@app.route('/api/v1/activate', methods=['POST'])
def activate_license():
    data = request.json or {}
    license_key = data.get('license_key')
    machine_id = data.get('machine_id')

    if not license_key or not machine_id:
        return jsonify({'status': 'FAIL', 'message': 'Missing info'}), 400

    license = License.query.filter_by(license_key=license_key).first()

    if not license:
        return jsonify({'status': 'FAIL', 'message': 'License not found.'}), 404
        
    if license.status != 'ACTIVE':
        return jsonify({'status': license.status, 'message': f'License is {license.status}.'}), 403

    if license.allowed_machine_id and license.allowed_machine_id != machine_id:
        return jsonify({'status': 'FAIL', 'message': 'Activated on another device.'}), 403
    
    license.allowed_machine_id = machine_id
    license.last_check = datetime.datetime.utcnow()
    license.activation_note = f"Activated ID: {machine_id[:10]}..."
    db.session.commit()
    
    return jsonify({
        'status': 'ACTIVATED', 
        'expiry_date': license.expiry_date.strftime('%Y-%m-%d')
    }), 200

# 3. KIỂM TRA ĐỊNH KỲ (Client gọi)
@app.route('/api/v1/validate', methods=['POST'])
def validate_license():
    data = request.json or {}
    license_key = data.get('license_key')
    machine_id = data.get('machine_id')

    if not license_key or not machine_id:
        return jsonify({'status': 'FAIL', 'message': 'Missing info'}), 400

    license = License.query.filter_by(license_key=license_key).first()

    if not license:
        return jsonify({'status': 'FAIL', 'message': 'License not found.'}), 404

    if license.expiry_date < datetime.date.today():
        license.status = 'EXPIRED'
        db.session.commit()
        return jsonify({'status': 'EXPIRED', 'message': 'Expired.'}), 403

    if license.status != 'ACTIVE':
        return jsonify({'status': license.status, 'message': f'License is {license.status}.'}), 403

    if license.allowed_machine_id != machine_id:
        return jsonify({'status': 'FAIL', 'message': 'Machine ID mismatch.'}), 403

    license.last_check = datetime.datetime.utcnow()
    db.session.commit()

    return jsonify({
        'status': 'OK', 
        'expiry_date': license.expiry_date.strftime('%Y-%m-%d')
    }), 200

# 4. GIA HẠN (Admin Tool gọi)
@app.route('/api/v1/extend', methods=['POST'])
def extend_license():
    data = request.json or {}
    if data.get('admin_key') != ADMIN_SECRET: return jsonify({'status': 'FAIL'}), 401
    
    license_key = data.get('license_key')
    days = data.get('days_to_add')

    license = License.query.filter_by(license_key=license_key).first()
    if not license: return jsonify({'status': 'FAIL', 'message': 'Not found'}), 404
    
    base_date = license.expiry_date if license.expiry_date >= datetime.date.today() else datetime.date.today()
    license.expiry_date = base_date + datetime.timedelta(days=days)
    license.status = 'ACTIVE'
    db.session.commit()

    return jsonify({
        'status': 'EXTENDED', 
        'new_expiry_date': license.expiry_date.strftime('%Y-%m-%d')
    }), 200

# 5. ĐỔI MÁY (Admin Tool gọi)
@app.route('/api/v1/relicense', methods=['POST'])
def relicense_key():
    data = request.json or {}
    if data.get('admin_key') != ADMIN_SECRET: return jsonify({'status': 'FAIL'}), 401
    
    license = License.query.filter_by(license_key=data.get('license_key')).first()
    if not license: return jsonify({'status': 'FAIL'}), 404

    license.allowed_machine_id = data.get('new_machine_id')
    license.status = 'ACTIVE'
    db.session.commit()

    return jsonify({'status': 'RE-LICENSED', 'new_machine_id': license.allowed_machine_id}), 200

if __name__ == '__main__':
    print("🚀 Running Local Mode...")
    app.run(debug=True, use_reloader=False)
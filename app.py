import os, sqlite3, secrets
from datetime import datetime, date, timedelta
from functools import wraps
from io import BytesIO
import base64
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify, abort
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import qrcode

load_dotenv()
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=3),
)
csrf = CSRFProtect(app)
DB = os.path.join(os.path.dirname(__file__), "database.db")

def connect():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS students(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, student_id TEXT NOT NULL UNIQUE, department TEXT, year TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS admins(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS parents(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, phone TEXT);
    CREATE TABLE IF NOT EXISTS parent_students(
      parent_id INTEGER NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      PRIMARY KEY(parent_id,student_id));
    CREATE TABLE IF NOT EXISTS drivers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, phone TEXT, licence TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS super_admins(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS routes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, route_name TEXT NOT NULL, bus_number TEXT NOT NULL,
      stops TEXT NOT NULL DEFAULT '', fee REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS buses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, bus_number TEXT UNIQUE NOT NULL, registration TEXT,
      capacity INTEGER, route_id INTEGER REFERENCES routes(id), driver_id INTEGER REFERENCES drivers(id));
    CREATE TABLE IF NOT EXISTS applications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES students(id),
      route_id INTEGER NOT NULL REFERENCES routes(id), pickup_stop TEXT NOT NULL,
      applied_on TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'Pending',
      valid_until TEXT, qr_token TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS stops(
      id INTEGER PRIMARY KEY AUTOINCREMENT, route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
      name TEXT NOT NULL, sequence INTEGER NOT NULL, latitude REAL, longitude REAL, UNIQUE(route_id,sequence));
    CREATE TABLE IF NOT EXISTS trips(
      id INTEGER PRIMARY KEY AUTOINCREMENT, bus_id INTEGER REFERENCES buses(id),
      driver_id INTEGER REFERENCES drivers(id), route_id INTEGER REFERENCES routes(id),
      status TEXT DEFAULT 'Scheduled', started_at TEXT, ended_at TEXT);
    CREATE TABLE IF NOT EXISTS gps_locations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
      latitude REAL NOT NULL, longitude REAL NOT NULL, speed REAL DEFAULT 0, heading REAL DEFAULT 0,
      recorded_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS idx_gps_trip_time ON gps_locations(trip_id,recorded_at);
    CREATE TABLE IF NOT EXISTS boarding_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL REFERENCES trips(id),
      application_id INTEGER NOT NULL REFERENCES applications(id), student_id INTEGER NOT NULL REFERENCES students(id),
      stop_id INTEGER REFERENCES stops(id), event_type TEXT NOT NULL DEFAULT 'boarded',
      boarded_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(trip_id,student_id,event_type));
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id), title TEXT NOT NULL, message TEXT NOT NULL,
      is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor_role TEXT, actor_id INTEGER, action TEXT,
      details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    # Preserve existing records; seed only missing initial accounts/routes.
    if db.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
        db.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)",
                   (os.getenv("ADMIN_USERNAME","admin"), generate_password_hash(os.getenv("ADMIN_PASSWORD","ChangeMe123!"))))
    if db.execute("SELECT COUNT(*) FROM super_admins").fetchone()[0] == 0:
        db.execute("INSERT INTO super_admins(username,password_hash) VALUES(?,?)",
                   (os.getenv("SUPERADMIN_USERNAME","superadmin"), generate_password_hash(os.getenv("SUPERADMIN_PASSWORD","ChangeMeSuper123!"))))
    # CampusMove starter network: Joy University is the hub for all route corridors.
    starter_routes = [
        ("01 · Tirunelveli Corridor", "CM-01", "Vadakkankulam,Kavalkinaru,Panagudi,Valliyur,Vadakkuvalliyur,Nanguneri,Kalakkad,Moolaikaraipatti,Manur,Tirunelveli,Cheranmahadevi,Kallidaikurichi,Ambasamudram", 8000),
        ("02 · Kanyakumari Corridor", "CM-02", "Radhapuram,Dhanakkarkulam,Chettikulam,Levinjipuram,Koodankulam,Uvari,Thisayanvilai,Nagercoil,Kanyakumari,Suchindram,Thovalai,Boothapandi,Thittuvilai,Aralvaimozhi,Azhagappapuram,Agastheeswaram,Kottaram,Anjugramam,Mylaudy,Rajakkamangalam,Eathamozhi,Parvathipuram", 9000),
        ("03 · Western Kanyakumari Corridor", "CM-03", "Thuckalay,Padmanabhapuram,Eraniel,Colachel,Manavalakurichi,Mandaikadu,Monday Market,Karungal,Marthandam,Kuzhithurai,Thiruvattar,Kulasekaram,Thirparappu", 9500),
        ("04 · Thoothukudi Corridor", "CM-04", "Tiruchendur,Sathankulam,Nazareth,Alwarthirunagari,Srivaikuntam,Eral,Sawyerpuram,Arumuganeri,Kayalpattinam,Authoor,Pudukottai,Thoothukudi,Kovilpatti,Ettayapuram,Vilathikulam", 10000),
        ("05 · Southern Kerala Corridor", "CM-05", "Neyyattinkara,Poovar,Vizhinjam,Balaramapuram,Parassala,Kaliyikkavila,Thiruvananthapuram,Kazhakkoottam,Attingal,Varkala,Punalur", 11000),
    ]
    existing = db.execute("SELECT route_name FROM routes ORDER BY id").fetchall()
    if not existing:
        db.executemany("INSERT INTO routes(route_name,bus_number,stops,fee) VALUES(?,?,?,?)", starter_routes)
    elif all(r[0].startswith("Route A -") or r[0].startswith("Route B -") or r[0].startswith("Route C -") for r in existing) and db.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0:
        db.execute("DELETE FROM stops")
        db.execute("DELETE FROM buses")
        db.execute("DELETE FROM routes")
        db.executemany("INSERT INTO routes(route_name,bus_number,stops,fee) VALUES(?,?,?,?)", starter_routes)
    for r in db.execute("SELECT id,bus_number,stops FROM routes").fetchall():
        db.execute("INSERT OR IGNORE INTO buses(bus_number,route_id) VALUES(?,?)",(r[1],r[0]))
        if db.execute("SELECT COUNT(*) FROM stops WHERE route_id=?",(r[0],)).fetchone()[0] == 0:
            db.executemany("INSERT OR IGNORE INTO stops(route_id,name,sequence) VALUES(?,?,?)",
                [(r[0],s.strip(),i) for i,s in enumerate((r[2] or "").split(","),1) if s.strip()])

    # Local demonstration accounts. Change these credentials before any deployment.
    demo = os.getenv("CAMPUSMOVE_DEMO_ACCOUNTS", "1") == "1"
    if demo:
        db.execute("INSERT OR IGNORE INTO students(name,email,password_hash,student_id,department,year) VALUES(?,?,?,?,?,?)",
            ("Demo Student", "student01@campusmove.demo", generate_password_hash("Student@12345"), "CM-DEMO-001", "B.Tech Cyber Security", "3rd Year"))
        db.execute("INSERT OR IGNORE INTO parents(name,email,password_hash,phone) VALUES(?,?,?,?)",
            ("Demo Parent", "parent01@campusmove.demo", generate_password_hash("Parent@12345"), "9000000001"))
        db.execute("INSERT OR IGNORE INTO drivers(name,email,password_hash,phone,licence) VALUES(?,?,?,?,?)",
            ("Demo Driver", "driver01@campusmove.demo", generate_password_hash("Driver@12345"), "9000000002", "DEMO-LICENCE"))
        db.execute("INSERT OR IGNORE INTO admins(username,password_hash) VALUES(?,?)",
            ("admin01@campusmove.demo", generate_password_hash("Admin@12345")))
        db.execute("INSERT OR IGNORE INTO super_admins(username,password_hash) VALUES(?,?)",
            ("superadmin01@campusmove.demo", generate_password_hash("SuperAdmin@12345")))
        student = db.execute("SELECT id FROM students WHERE email=?",("student01@campusmove.demo",)).fetchone()
        parent = db.execute("SELECT id FROM parents WHERE email=?",("parent01@campusmove.demo",)).fetchone()
        driver = db.execute("SELECT id FROM drivers WHERE email=?",("driver01@campusmove.demo",)).fetchone()
        bus = db.execute("SELECT id FROM buses ORDER BY id LIMIT 1").fetchone()
        if student and parent:
            db.execute("INSERT OR IGNORE INTO parent_students(parent_id,student_id) VALUES(?,?)",(parent[0],student[0]))
        if driver and bus:
            db.execute("UPDATE buses SET driver_id=? WHERE id=? AND (driver_id IS NULL OR driver_id=?)",(driver[0],bus[0],driver[0]))
    db.commit(); db.close()

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            if not session.get("role"): return redirect(url_for("login"))
            if session["role"] not in roles: abort(403)
            return fn(*a,**kw)
        return wrapped
    return deco

def audit(action, details=""):
    connect().execute("INSERT INTO audit_logs(actor_role,actor_id,action,details) VALUES(?,?,?,?)",
                      (session.get("role"),session.get("user_id"),action,details))
    connect().commit()

def notify_parents(student_id, title, message):
    db=connect()
    parents=db.execute("SELECT parent_id FROM parent_students WHERE student_id=?",(student_id,)).fetchall()
    db.executemany("INSERT INTO notifications(parent_id,student_id,title,message) VALUES(?,?,?,?)",
                   [(p["parent_id"],student_id,title,message) for p in parents])
    db.commit()

def dashboard_endpoint(role):
    return {"student":"student_dashboard","parent":"parent_dashboard","admin":"admin_dashboard",
            "super_admin":"superadmin_dashboard","driver":"driver_dashboard"}[role]

@app.context_processor
def context():
    return {"current_user":session.get("name"),"current_role":session.get("role")}

@app.route("/")
def home():
    if session.get("role"):
        return redirect(url_for(dashboard_endpoint(session["role"])))
    return redirect(url_for("login"))
    db=connect()
    stats=[db.execute("SELECT COUNT(*) FROM students").fetchone()[0],
           db.execute("SELECT COUNT(*) FROM routes").fetchone()[0],
           db.execute("SELECT COUNT(*) FROM buses").fetchone()[0],
           db.execute("SELECT COUNT(*) FROM trips WHERE status='Active'").fetchone()[0]]
    routes=db.execute("SELECT * FROM routes ORDER BY id").fetchall()
    return render_template("home.html",stats=stats,routes=routes)

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        identity=request.form.get("identity","").strip()
        password=request.form.get("password","")
        db=connect()
        candidates=[
          ("student","SELECT id,name,email,password_hash FROM students WHERE lower(email)=lower(?)",(identity,)),
          ("parent","SELECT id,name,email,password_hash FROM parents WHERE lower(email)=lower(?)",(identity,)),
          ("driver","SELECT id,name,email,password_hash FROM drivers WHERE lower(email)=lower(?) AND active=1",(identity,)),
          ("admin","SELECT id,username AS name,username AS email,password_hash FROM admins WHERE lower(username)=lower(?)",(identity,)),
          ("super_admin","SELECT id,username AS name,username AS email,password_hash FROM super_admins WHERE lower(username)=lower(?)",(identity,))
        ]
        # A username/email must resolve to exactly one active account; ambiguous identities are denied.
        matches=[]
        for role,sql,args in candidates:
            row=db.execute(sql,args).fetchone()
            if row and check_password_hash(row["password_hash"],password): matches.append((role,row))
        if len(matches)==1:
            role,row=matches[0]
            session.clear(); session.permanent=True
            session.update(role=role,user_id=row["id"],name=row["name"])
            audit("login","Successful universal login")
            return redirect(url_for(dashboard_endpoint(role)))
        flash("Invalid credentials or ambiguous account. Contact the transport administrator.","error")
    return render_template("login.html")

@app.route("/logout",methods=["POST"])
@role_required("student","parent","driver","admin","super_admin")
def logout():
    session.clear(); flash("You have been logged out.","success"); return redirect(url_for("home"))

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        f=request.form; name=f.get("name","").strip(); email=f.get("email","").strip().lower()
        sid=f.get("student_id","").strip(); pw=f.get("password","")
        if not all([name,email,sid,pw]) or len(pw)<8: flash("Complete all fields; password must be at least 8 characters.","error")
        else:
            try:
                connect().execute("INSERT INTO students(name,email,password_hash,student_id,department,year) VALUES(?,?,?,?,?,?)",
                    (name,email,generate_password_hash(pw),sid,f.get("department",""),f.get("year","")))
                connect().commit(); flash("Student account created. Sign in now.","success"); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("Email or register number already exists.","error")
    return render_template("register.html")

@app.route("/profile", methods=["GET", "POST"])
@role_required("student", "parent", "driver", "admin", "super_admin")
def profile():
    db=connect(); role=session["role"]; uid=session["user_id"]
    tables={"student":("students", "id"), "parent":("parents", "id"), "driver":("drivers", "id"), "admin":("admins", "id"), "super_admin":("super_admins", "id")}
    table,key=tables[role]
    row=db.execute(f"SELECT * FROM {table} WHERE {key}=?",(uid,)).fetchone()
    if request.method=="POST":
        name=request.form.get("name","").strip(); phone=request.form.get("phone","").strip()
        if role in ("admin", "super_admin"):
            flash("Administrator account profile is managed by the system owner.","error")
        elif not name:
            flash("Name cannot be empty.","error")
        else:
            db.execute(f"UPDATE {table} SET name=?" + (", phone=?" if role in ("parent","driver") else "") + f" WHERE {key}=?", (name,phone,uid) if role in ("parent","driver") else (name,uid))
            db.commit(); session["name"]=name; audit("profile_updated",role); flash("Profile updated.","success"); return redirect(url_for("profile"))
        row=db.execute(f"SELECT * FROM {table} WHERE {key}=?",(uid,)).fetchone()
    return render_template("profile.html",profile=row,role=role)

@app.route("/tracking")
@role_required("student", "parent", "admin", "super_admin")
def tracking():
    return render_template("tracking.html")

@app.route("/student")
@role_required("student")
def student_dashboard():
    db=connect()
    student=db.execute("SELECT * FROM students WHERE id=?",(session["user_id"],)).fetchone()
    apps=db.execute("""SELECT a.*,r.route_name,r.bus_number,r.fee FROM applications a JOIN routes r ON r.id=a.route_id
                       WHERE a.student_id=? ORDER BY a.id DESC""",(student["id"],)).fetchall()
    return render_template("student.html",student=student,applications=apps)

@app.route("/student/apply",methods=["GET","POST"])
@role_required("student")
def apply_pass():
    db=connect(); routes=db.execute("SELECT * FROM routes").fetchall()
    if request.method=="POST":
        rid=request.form.get("route_id",type=int); stop=request.form.get("pickup_stop","").strip()
        route=db.execute("SELECT * FROM routes WHERE id=?",(rid,)).fetchone()
        if not route or stop not in [x.strip() for x in route["stops"].split(",")]:
            flash("Choose a valid route and pickup stop.","error")
        else:
            db.execute("INSERT INTO applications(student_id,route_id,pickup_stop) VALUES(?,?,?)",(session["user_id"],rid,stop))
            db.commit(); flash("Application sent for approval.","success"); return redirect(url_for("student_dashboard"))
    return render_template("apply.html",routes=routes)

@app.route("/pass/<int:aid>")
@role_required("student")
def digital_pass(aid):
    row=connect().execute("""SELECT a.*,s.name,s.student_id,r.route_name,r.bus_number FROM applications a
      JOIN students s ON s.id=a.student_id JOIN routes r ON r.id=a.route_id WHERE a.id=? AND a.student_id=? AND a.status='Approved'""",
      (aid,session["user_id"])).fetchone()
    if not row or not row["qr_token"]: abort(404)
    img=qrcode.make(url_for("verify_pass",token=row["qr_token"],_external=True)); buf=BytesIO(); img.save(buf,format="PNG")
    qr="data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode()
    return render_template("pass.html",item=row,qr=qr)

@app.route("/verify/<token>")
def verify_pass(token):
    row=connect().execute("""SELECT a.status,a.valid_until,s.name,s.student_id,r.route_name,r.bus_number,a.pickup_stop
      FROM applications a JOIN students s ON s.id=a.student_id JOIN routes r ON r.id=a.route_id WHERE a.qr_token=?""",(token,)).fetchone()
    valid=bool(row and row["status"]=="Approved" and row["valid_until"] and row["valid_until"]>=date.today().isoformat())
    return render_template("verify.html",item=row,is_valid=valid), (200 if row else 404)

@app.route("/parent")
@role_required("parent")
def parent_dashboard():
    db=connect()
    children=db.execute("""SELECT s.* FROM students s JOIN parent_students ps ON ps.student_id=s.id
                           WHERE ps.parent_id=?""",(session["user_id"],)).fetchall()
    notes=db.execute("""SELECT n.*,s.name AS student_name FROM notifications n JOIN students s ON s.id=n.student_id
                        WHERE n.parent_id=? ORDER BY n.id DESC LIMIT 50""",(session["user_id"],)).fetchall()
    child_data=[]
    for child in children:
        latest=db.execute("""SELECT a.*,r.route_name,r.bus_number FROM applications a JOIN routes r ON r.id=a.route_id
                             WHERE a.student_id=? AND a.status='Approved' ORDER BY a.id DESC LIMIT 1""",(child["id"],)).fetchone()
        child_data.append((child,latest))
    return render_template("parent.html",children=child_data,notifications=notes)

@app.route("/parent/notifications/read",methods=["POST"])
@role_required("parent")
def read_notifications():
    connect().execute("UPDATE notifications SET is_read=1 WHERE parent_id=?",(session["user_id"],))
    connect().commit(); return redirect(url_for("parent_dashboard"))

@app.route("/driver")
@role_required("driver")
def driver_dashboard():
    db=connect()
    bus=db.execute("""SELECT b.*,r.route_name,r.stops FROM buses b LEFT JOIN routes r ON r.id=b.route_id
                      WHERE b.driver_id=?""",(session["user_id"],)).fetchone()
    trip=db.execute("SELECT * FROM trips WHERE driver_id=? AND status='Active' ORDER BY id DESC LIMIT 1",
                    (session["user_id"],)).fetchone()
    return render_template("driver.html",bus=bus,trip=trip)

@app.route("/driver/trip/start",methods=["POST"])
@role_required("driver")
def start_trip():
    db=connect()
    bus=db.execute("SELECT * FROM buses WHERE driver_id=?",(session["user_id"],)).fetchone()
    if not bus: flash("No bus is assigned to your driver account.","error")
    else:
        db.execute("UPDATE trips SET status='Completed',ended_at=CURRENT_TIMESTAMP WHERE driver_id=? AND status='Active'",(session["user_id"],))
        db.execute("INSERT INTO trips(bus_id,driver_id,route_id,status,started_at) VALUES(?,?,?,'Active',CURRENT_TIMESTAMP)",
                   (bus["id"],session["user_id"],bus["route_id"]))
        db.commit(); audit("trip_started",f"Bus {bus['bus_number']}")
        flash("Trip started. Allow location access to share GPS.","success")
    return redirect(url_for("driver_dashboard"))

@app.route("/driver/trip/end",methods=["POST"])
@role_required("driver")
def end_trip():
    db=connect()
    db.execute("UPDATE trips SET status='Completed',ended_at=CURRENT_TIMESTAMP WHERE driver_id=? AND status='Active'",(session["user_id"],))
    db.commit(); audit("trip_ended","Driver ended trip"); flash("Trip ended.","success")
    return redirect(url_for("driver_dashboard"))

@app.route("/api/driver/location",methods=["POST"])
@role_required("driver")
def save_location():
    data=request.get_json(silent=True) or {}
    try: lat=float(data["latitude"]); lng=float(data["longitude"])
    except (KeyError,TypeError,ValueError): return jsonify(error="Valid latitude and longitude required"),400
    if not (-90<=lat<=90 and -180<=lng<=180): return jsonify(error="Coordinates out of range"),400
    db=connect(); trip=db.execute("SELECT id FROM trips WHERE driver_id=? AND status='Active' ORDER BY id DESC LIMIT 1",(session["user_id"],)).fetchone()
    if not trip: return jsonify(error="No active trip"),409
    db.execute("INSERT INTO gps_locations(trip_id,latitude,longitude,speed,heading) VALUES(?,?,?,?,?)",
               (trip["id"],lat,lng,float(data.get("speed") or 0),float(data.get("heading") or 0)))
    db.commit(); return jsonify(ok=True)

@app.route("/driver/boarding",methods=["POST"])
@role_required("driver")
def record_boarding():
    db=connect()
    f=request.form
    raw=f.get("qr_value","").strip()
    event=f.get("event_type","boarded")
    if event not in ("boarded","alighted"):
        flash("Invalid boarding event.","error")
        return redirect(url_for("driver_dashboard"))
    # QR may contain the full public verification URL or just the opaque token.
    token=raw.rstrip("/").split("/")[-1]
    trip=db.execute("SELECT * FROM trips WHERE driver_id=? AND status='Active' ORDER BY id DESC LIMIT 1",
                    (session["user_id"],)).fetchone()
    app_row=db.execute("""SELECT a.*,s.name,s.id AS sid,r.route_name FROM applications a
        JOIN students s ON s.id=a.student_id JOIN routes r ON r.id=a.route_id
        WHERE a.qr_token=? AND a.status='Approved'""",(token,)).fetchone()
    if not trip:
        flash("Start an active trip before scanning passes.","error")
    elif not app_row or app_row["route_id"] != trip["route_id"]:
        flash("QR pass is invalid or does not belong to this trip's route.","error")
    elif app_row["valid_until"] and app_row["valid_until"] < date.today().isoformat():
        flash("This transport pass has expired.","error")
    else:
        try:
            db.execute("""INSERT INTO boarding_records(trip_id,application_id,student_id,event_type)
                VALUES(?,?,?,?)""",(trip["id"],app_row["id"],app_row["sid"],event))
            db.commit()
            verb="boarded the bus" if event=="boarded" else "got off the bus"
            notify_parents(app_row["sid"],"Student "+verb,
                           f"{app_row['name']} {verb} on {app_row['route_name']} at {datetime.now().strftime('%d %b %Y, %I:%M %p')}.")
            audit("student_"+event,app_row["name"])
            flash(f"{app_row['name']} recorded: {event}. Parent notification created.","success")
        except sqlite3.IntegrityError:
            flash(f"This {event} event has already been recorded for this student on this trip.","error")
    return redirect(url_for("driver_dashboard"))

@app.route("/api/trips")
@role_required("student","parent","admin","super_admin")
def active_trips():
    rows=connect().execute("""SELECT t.id,b.bus_number,r.route_name,g.latitude,g.longitude,g.speed,g.recorded_at
      FROM trips t JOIN buses b ON b.id=t.bus_id LEFT JOIN routes r ON r.id=t.route_id
      LEFT JOIN gps_locations g ON g.id=(SELECT MAX(id) FROM gps_locations WHERE trip_id=t.id)
      WHERE t.status='Active'""").fetchall()
    return jsonify([dict(x) for x in rows])

@app.route("/admin")
@role_required("admin","super_admin")
def admin_dashboard():
    db=connect()
    apps=db.execute("""SELECT a.*,s.name,s.student_id,s.email,r.route_name,r.bus_number FROM applications a
      JOIN students s ON s.id=a.student_id JOIN routes r ON r.id=a.route_id ORDER BY a.id DESC""").fetchall()
    routes=db.execute("SELECT * FROM routes ORDER BY id DESC").fetchall()
    counts=[db.execute("SELECT COUNT(*) FROM students").fetchone()[0],db.execute("SELECT COUNT(*) FROM parents").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM drivers").fetchone()[0],db.execute("SELECT COUNT(*) FROM buses").fetchone()[0]]
    buses=db.execute("SELECT b.*,r.route_name,d.name AS driver_name FROM buses b LEFT JOIN routes r ON r.id=b.route_id LEFT JOIN drivers d ON d.id=b.driver_id ORDER BY b.bus_number").fetchall()
    drivers=db.execute("SELECT id,name,email FROM drivers WHERE active=1 ORDER BY name").fetchall()
    return render_template("admin.html",applications=apps,routes=routes,counts=counts,buses=buses,drivers=drivers)

@app.route("/admin/application/<int:aid>/<action>",methods=["POST"])
@role_required("admin","super_admin")
def review_application(aid,action):
    if action not in ("approve","reject"): abort(404)
    db=connect(); row=db.execute("SELECT * FROM applications WHERE id=?",(aid,)).fetchone()
    if not row: abort(404)
    if action=="approve":
        db.execute("UPDATE applications SET status='Approved',valid_until=?,qr_token=? WHERE id=?",
                   ((date.today()+timedelta(days=180)).isoformat(),secrets.token_urlsafe(32),aid))
    else: db.execute("UPDATE applications SET status='Rejected',qr_token=NULL WHERE id=?",(aid,))
    db.commit(); audit("application_"+action,str(aid))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/route/add",methods=["POST"])
@role_required("admin","super_admin")
def add_route():
    f=request.form; name=f.get("route_name","").strip(); bus=f.get("bus_number","").strip()
    stops=f.get("stops","").strip(); fee=f.get("fee",type=float)
    if not name or not bus or not stops or fee is None or fee<0: flash("Enter valid route details.","error")
    else:
        db=connect(); cur=db.execute("INSERT INTO routes(route_name,bus_number,stops,fee) VALUES(?,?,?,?)",(name,bus,stops,fee))
        rid=cur.lastrowid; db.execute("INSERT OR IGNORE INTO buses(bus_number,route_id) VALUES(?,?)",(bus,rid))
        db.executemany("INSERT INTO stops(route_id,name,sequence) VALUES(?,?,?)",
          [(rid,s.strip(),i) for i,s in enumerate(stops.split(","),1) if s.strip()])
        db.commit(); audit("route_added",name); flash("Route added.","success")
    return redirect(url_for("admin_dashboard"))

@app.route("/superadmin")
@role_required("super_admin")
def superadmin_dashboard():
    db=connect()
    metrics={t:db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ["students","parents","drivers","admins","buses","routes","trips"]}
    logs=db.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 30").fetchall()
    return render_template("superadmin.html",metrics=metrics,logs=logs)

@app.route("/superadmin/create-user",methods=["POST"])
@role_required("super_admin")
def create_user():
    f=request.form; role=f.get("role"); name=f.get("name","").strip(); identity=f.get("identity","").strip(); pw=f.get("password","")
    if role not in ("admin","driver","parent") or not name or not identity or len(pw)<10:
        flash("Provide valid details. Password must be at least 10 characters.","error")
    else:
        db=connect()
        try:
            if role=="admin": db.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)",(identity,generate_password_hash(pw)))
            elif role=="driver": db.execute("INSERT INTO drivers(name,email,password_hash) VALUES(?,?,?)",(name,identity,generate_password_hash(pw)))
            else: db.execute("INSERT INTO parents(name,email,password_hash) VALUES(?,?,?)",(name,identity,generate_password_hash(pw)))
            db.commit(); audit("account_created",f"{role}: {identity}"); flash(f"{role.title()} account created.","success")
        except sqlite3.IntegrityError: flash("That username or email already exists.","error")
    return redirect(url_for("superadmin_dashboard"))

@app.route("/superadmin/link-parent",methods=["POST"])
@role_required("super_admin")
def link_parent():
    f=request.form; parent=connect().execute("SELECT id FROM parents WHERE email=?",(f.get("parent_email","").strip().lower(),)).fetchone()
    student=connect().execute("SELECT id FROM students WHERE student_id=?",(f.get("student_code","").strip(),)).fetchone()
    if not parent or not student: flash("Parent email or student register number not found.","error")
    else:
        try:
            connect().execute("INSERT INTO parent_students(parent_id,student_id) VALUES(?,?)",(parent["id"],student["id"]))
            connect().commit(); audit("parent_student_linked",f.get("student_code")); flash("Parent linked to student.","success")
        except sqlite3.IntegrityError: flash("This parent-child link already exists.","error")
    return redirect(url_for("superadmin_dashboard"))


@app.route("/admin/bus/add",methods=["POST"])
@role_required("admin","super_admin")
def admin_add_bus():
    f=request.form; number=f.get("bus_number","").strip().upper(); registration=f.get("registration","").strip(); capacity=f.get("capacity",type=int); route_id=f.get("route_id",type=int)
    if not number or (capacity is not None and capacity<1): flash("Enter a valid bus number and capacity.","error")
    else:
        try:
            connect().execute("INSERT INTO buses(bus_number,registration,capacity,route_id) VALUES(?,?,?,?)",(number,registration,capacity,route_id or None)); connect().commit(); audit("bus_created",number); flash("Bus added successfully.","success")
        except sqlite3.IntegrityError: flash("That bus number already exists or the route is invalid.","error")
    return redirect(url_for("admin_dashboard")+"#fleet")

@app.route("/admin/driver/assign",methods=["POST"])
@role_required("admin","super_admin")
def admin_assign_driver():
    driver_id=request.form.get("driver_id",type=int); bus_id=request.form.get("bus_id",type=int)
    if not driver_id or not bus_id: flash("Select both a driver and a bus.","error")
    else:
        cur=connect().execute("UPDATE buses SET driver_id=? WHERE id=?",(driver_id,bus_id)); connect().commit()
        if cur.rowcount: audit("driver_assigned",f"driver={driver_id}; bus={bus_id}"); flash("Driver assigned to bus.","success")
        else: flash("Bus not found.","error")
    return redirect(url_for("admin_dashboard")+"#fleet")

@app.route("/admin/bus/<int:bus_id>/route",methods=["POST"])
@role_required("admin","super_admin")
def admin_change_bus_route(bus_id):
    route_id=request.form.get("route_id",type=int)
    if route_id and not connect().execute("SELECT 1 FROM routes WHERE id=?",(route_id,)).fetchone(): abort(404)
    connect().execute("UPDATE buses SET route_id=? WHERE id=?",(route_id,bus_id)); connect().commit(); audit("bus_route_changed",str(bus_id)); flash("Bus route updated.","success"); return redirect(url_for("admin_dashboard")+"#fleet")

@app.errorhandler(403)
def forbidden(_): return render_template("error.html",code=403,message="Your account does not have permission for this page."),403
@app.errorhandler(404)
def missing(_): return render_template("error.html",code=404,message="The requested page was not found."),404

if __name__=="__main__":
    init_db()
    app.run(host="127.0.0.1",port=5000,debug=False)

## pgAdmin Guide

---

### First Time Login

1. Open [http://localhost:5050](http://localhost:5050) in your browser
2. Log in with:
   - Email: `admin@admin.com`
   - Password: `admin`

---

### Adding the PoliSense Server (First Time Only)

1. In the left panel, right-click **Servers** → **Register** → **Server**
2. **General tab:**
   - Name: `polisense` (just a label, can be anything)
3. **Connection tab:**
   - Host: `polisense_postgres`
   - Port: `5432`
   - Database: `polisense_db_dev`
   - Username: `polisense_user`
   - Password: `polisense_password`
   - Check **Save password** so you don't have to re-enter it
4. Click **Save**
5. You should now see `polisense` appear in the left panel under **Servers**

---

### Subsequent Logins

1. Open [http://localhost:5050](http://localhost:5050)
2. Log in with `admin@admin.com` / `admin`
3. In the left panel, expand **Servers → polisense → Databases → polisense_db_dev → Schemas → public → Tables**
4. Your server and connection details are already saved — no need to re-enter them

---

### Browsing Table Data

1. In the left panel, navigate to **Servers → polisense → Databases → polisense_db_dev → Schemas → public → Tables**
2. Right-click a table (e.g. `policies`) → **View/Edit Data** → **All Rows**
3. Data will display in a spreadsheet-like view on the right

---

### Running Queries

1. Click **Tools** in the top menu → **Query Tool**  
   (or right-click the database → **Query Tool**)
2. Type your SQL query in the top panel, e.g.:
```sql
   SELECT policy_name, industry, geography FROM policies LIMIT 10;
```
3. Click the **▶ Play** button (or press `F5`) to run
4. Results appear in the bottom panel

---

### Troubleshooting

| Problem | Fix |
|---|---|
| Can't open localhost:5050 | Run `docker compose up -d` first |
| Password prompt on every login | Check **Save password** when registering the server |
| Server shows as disconnected | Right-click server → **Connect** |
| No tables visible | Make sure you ran the schema or backup SQL after starting the container |
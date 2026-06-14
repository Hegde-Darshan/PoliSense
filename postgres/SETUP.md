## Commands for PostgreSQL DB

### Start Docker Container
```powershell
docker compose up -d
```

### Create New Database
```powershell
Get-Content postgres/database_create.sql | docker exec -i polisense_postgres psql -U polisense_user -d postgres
```

### Restore from Backup
```powershell
Get-Content backup.sql | docker exec -i polisense_postgres psql -U polisense_user -d postgres
```

### Connect to Database (terminal)
```powershell
docker exec -it polisense_postgres psql -U polisense_user -d polisense_db_dev
```

### Run Test Queries
```powershell
Get-Content postgres/test_queries.sql | docker exec -i polisense_postgres psql -U polisense_user -d polisense_db_dev
```

### Useful psql Commands (once connected)
```sql
\dt                            -- list all tables
SELECT COUNT(*) FROM policies; -- count rows
\q                             -- quit
```

---

## pgAdmin Setup (GUI)

1. Open [http://localhost:5050](http://localhost:5050) in your browser
2. Log in with:
   - Email: `admin@admin.com`
   - Password: `admin`
3. Go to **Object > Register > Server**
4. **General tab:**
   - Name: `polisense` (or anything you like)
5. **Connection tab:**
   - Host: `polisense_postgres`
   - Port: `5432`
   - Database: `polisense_db_dev`
   - Username: `polisense_user`
   - Password: `polisense_password`
6. Click **Save** — you should now see the database in the left panel
# PoliSense
This is an intelligent policy filtering and ranking system, to help you find government grants/schemes and policies based on your requirements.  
All you have to do is give this a priliminary details about your company and what you are looking for. And, this will do the rest!
***


## Running ChromaDB for the first time
- [ ] Install ChromaDB and make sure docker-compose.yml has chromadb service
- [ ] From project root, run - <docker compose up -d>
- [ ] To verify it's running, run - <docker ps> or check health with - <curl http://localhost:8000/api/v2/heartbeat>

## Booting up again or to restart
- [ ] To restart service, run - <docker compose down>
- [ ] To start service, run - <docker compose up -d>

## Using Makefile to run services
- [ ] Ensure Makefile exists and WSL is installed, and has <make> installed in it
- [ ] Docker Desktop is enabled with WSL2 engine
- [ ] Run <make help> to view available commands
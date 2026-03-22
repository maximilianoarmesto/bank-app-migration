# Bank App Migration (SIA)

A modern banking application migration system built with FastAPI, Next.js, PostgreSQL, and Docker.

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy
- **Frontend**: Next.js, TypeScript, React
- **Database**: PostgreSQL
- **Containerization**: Docker, Docker Compose
- **ORM**: SQLAlchemy
- **API Documentation**: Swagger UI (via FastAPI)

## Project Structure

```
├── backend/                 # FastAPI backend application
│   ├── app/                # Application code
│   ├── alembic/            # Database migrations
│   ├── requirements.txt    # Python dependencies
│   └── Dockerfile         # Backend container
├── frontend/               # Next.js frontend application
│   ├── src/               # Source code
│   ├── public/            # Static assets
│   ├── package.json       # Node dependencies
│   └── Dockerfile         # Frontend container
├── docker-compose.yml     # Multi-container setup
├── .env.example          # Environment variables template
└── README.md            # Project documentation
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for local development)
- Python 3.11+ (for local development)

### Development Setup

1. Clone the repository and navigate to the project directory

2. Copy environment variables:
   ```bash
   cp .env.example .env
   ```

3. Start the development environment:
   ```bash
   docker-compose up -d
   ```

4. Access the applications:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs

### Local Development (without Docker)

#### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

Copy `.env.example` to `.env` and configure the following variables:

- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: JWT secret key
- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password
- `POSTGRES_DB`: Database name

## API Documentation

Once the backend is running, visit http://localhost:8000/docs for interactive API documentation powered by Swagger UI.

## Database Migrations

```bash
cd backend
alembic upgrade head
```

## License

This project is licensed under the MIT License.
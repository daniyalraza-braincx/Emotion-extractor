# Authentication Setup

A minimal authentication system has been added to protect the application. Users must log in with credentials stored in environment variables.

## Backend Configuration

Add these environment variables to your `.env` file in the `api/` directory:

```env
# Authentication credentials
AUTH_USERNAME=your_username
AUTH_PASSWORD=your_password

# JWT secret key (change this in production!)
JWT_SECRET_KEY=your-secret-key-change-in-production
```

### Environment Variables

- **`AUTH_USERNAME`** - Username for login (default: "admin")
- **`AUTH_PASSWORD`** - Password for login (default: "password")
- **`JWT_SECRET_KEY`** - Secret key for JWT token signing (default: "your-secret-key-change-in-production")
  - **Important**: Change this to a strong random string in production!

## Backend Dependencies

New dependencies added to `api/requirements.txt`:
- `pyjwt` - For JWT token creation and verification
- `passlib[bcrypt]` - For password hashing (currently using simple comparison, but included for future use)

Install with:
```bash
pip install -r api/requirements.txt
```

## API Endpoints

### Authentication Endpoints

- **`POST /auth/login`** - Login with username and password
  - Request: `{ "username": "...", "password": "..." }`
  - Response: `{ "success": true, "access_token": "...", "token_type": "bearer" }`

- **`GET /auth/verify`** - Verify if current token is valid
  - Requires: Bearer token in Authorization header
  - Response: `{ "success": true, "authenticated": true, "username": "..." }`

- **`POST /auth/logout`** - Logout (client-side token removal)
  - Response: `{ "success": true, "message": "Logged out successfully" }`

### Protected Endpoints

All API endpoints except `/` (health check) and `/retell/webhook` now require authentication:
- `POST /analyze`
- `GET /retell/calls`
- `POST /retell/calls/refresh`
- `POST /retell/calls/{call_id}/analyze`
- `GET /retell/calls/{call_id}/analysis`

## Frontend

### Login Page

A new login page is available at `/login`. Users will be redirected here if not authenticated.

### Protected Routes

All routes except `/login` are protected and require authentication:
- `/` - Dashboard
- `/analysis` - Analysis page

### Authentication Flow

1. User visits any protected route
2. If not authenticated, redirected to `/login`
3. User enters credentials
4. On successful login, JWT token is stored in localStorage
5. Token is included in all API requests via Authorization header
6. Token is verified on each protected route access

### Logout

A logout button is available in the Dashboard toolbar. Clicking it removes the token and redirects to login.

## Security Notes

⚠️ **Important for Production:**

1. **Change JWT_SECRET_KEY** - Use a strong, random secret key
2. **Use HTTPS** - JWT tokens should only be transmitted over HTTPS
3. **Token Expiration** - Tokens expire after 24 hours (configurable via `JWT_EXPIRATION_HOURS`)
4. **Password Security** - Consider implementing password hashing for production
5. **Rate Limiting** - Consider adding rate limiting to the login endpoint
6. **CORS** - Update CORS settings to restrict origins in production

## Testing

1. Start the backend: `cd api && python api_server.py`
2. Start the frontend: `cd web && npm run dev`
3. Visit the app - you'll be redirected to `/login`
4. Enter credentials from your `.env` file
5. You'll be redirected to the dashboard after successful login


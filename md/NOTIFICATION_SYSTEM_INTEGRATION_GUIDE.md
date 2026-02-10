# GST Billing - Notification System Integration Guide

## 📋 Table of Contents
1. [System Architecture](#system-architecture)
2. [Database Model](#database-model)
3. [REST API Endpoints](#rest-api-endpoints)
4. [WebSocket Connection](#websocket-connection)
5. [Authentication](#authentication)
6. [Third-Party Integration](#third-party-integration)
7. [Mobile App Integration](#mobile-app-integration)
8. [Standalone HTML Client](#standalone-html-client)
9. [Desktop App Integration](#desktop-app-integration)
10. [Code Examples](#code-examples)

---

## 🏗️ System Architecture

The notification system consists of three main components:

### 1. **Database Layer** (Django ORM)
- Model: `Notification`
- Storage: SQLite (default), can be PostgreSQL/MySQL
- Features: Soft delete, read tracking, timestamps

### 2. **REST API Layer** (HTTP/HTTPS)
- Protocol: HTTP/HTTPS
- Authentication: Django Session/Cookie-based
- Format: JSON
- Base URL: `http://127.0.0.1:8000` (development)

### 3. **Real-Time Layer** (WebSocket)
- Protocol: WebSocket (ws:// or wss://)
- Framework: Django Channels
- Transport: InMemoryChannelLayer (dev) / Redis (production)
- URL: `ws://127.0.0.1:8000/ws/notifications/`

---

## 📊 Database Model

### Notification Model Structure

```python
class Notification(models.Model):
    # User relationship
    user = ForeignKey(User)  # Who receives the notification
    
    # Content
    notification_type = CharField(max_length=20)  # Type of notification
    title = CharField(max_length=200)             # Short title
    message = TextField()                         # Full message
    
    # Navigation (optional)
    link_url = CharField(max_length=500)          # URL to navigate
    link_text = CharField(max_length=100)         # Button text
    
    # Status
    is_read = BooleanField(default=False)         # Read status
    is_deleted = BooleanField(default=False)      # Soft delete
    
    # Timestamps
    created_at = DateTimeField(auto_now_add=True) # Creation time
    read_at = DateTimeField(null=True)            # When marked read
    
    # Optional: Link to related objects
    related_object_type = CharField(max_length=50) # Model name
    related_object_id = IntegerField()             # Object ID
```

### Notification Types

| Type | Code | Description |
|------|------|-------------|
| Information | `INFO` | General information |
| Success | `SUCCESS` | Success messages |
| Warning | `WARNING` | Warning alerts |
| Error | `ERROR` | Error notifications |
| Invoice | `INVOICE` | Invoice-related |
| Quotation | `QUOTATION` | Quotation/Order related |
| Order | `ORDER` | Order updates |
| Customer | `CUSTOMER` | Customer-related |
| Product | `PRODUCT` | Product updates |
| Payment | `PAYMENT` | Payment notifications |
| System | `SYSTEM` | System alerts |

---

## 🔌 REST API Endpoints

### Base URL
```
http://127.0.0.1:8000
```

### 1. **Get Notifications List**

**Endpoint:** `GET /notifications/api/`

**Description:** Fetch paginated list of notifications

**Query Parameters:**
- `limit` (int, default: 10) - Number of notifications per page
- `offset` (int, default: 0) - Starting position
- `unread_only` (boolean, default: false) - Filter unread only

**Request Example:**
```bash
GET /notifications/api/?limit=20&offset=0&unread_only=false
Cookie: sessionid=your_session_id
```

**Response (200 OK):**
```json
{
  "success": true,
  "notifications": [
    {
      "id": 123,
      "type": "ORDER",
      "title": "New Order Received",
      "message": "Order #1234 has been placed by Customer ABC",
      "link_url": "/mobile_v1/admin/orders/123/",
      "link_text": "View Order",
      "is_read": false,
      "created_at": "2026-01-31 10:30:00",
      "icon_class": "bi-cart-fill text-primary",
      "badge_class": "badge-primary"
    }
  ],
  "unread_count": 5,
  "total_count": 50,
  "has_more": true
}
```

---

### 2. **Get Unread Count**

**Endpoint:** `GET /notifications/api/count/`

**Description:** Get only the unread notification count (lightweight)

**Request Example:**
```bash
GET /notifications/api/count/
Cookie: sessionid=your_session_id
```

**Response (200 OK):**
```json
{
  "success": true,
  "unread_count": 5
}
```

---

### 3. **Mark Notification as Read**

**Endpoint:** `POST /notifications/{notification_id}/mark-read/`

**Description:** Mark a specific notification as read

**Request Example:**
```bash
POST /notifications/123/mark-read/
Cookie: sessionid=your_session_id
X-CSRFToken: csrf_token_value
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Notification marked as read",
  "unread_count": 4
}
```

---

### 4. **Mark All as Read**

**Endpoint:** `POST /notifications/mark-all-read/`

**Description:** Mark all user's notifications as read

**Request Example:**
```bash
POST /notifications/mark-all-read/
Cookie: sessionid=your_session_id
X-CSRFToken: csrf_token_value
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "All notifications marked as read",
  "unread_count": 0
}
```

---

### 5. **Delete Notification**

**Endpoint:** `POST /notifications/{notification_id}/delete/`

**Description:** Soft delete a notification

**Request Example:**
```bash
POST /notifications/123/delete/
Cookie: sessionid=your_session_id
X-CSRFToken: csrf_token_value
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Notification deleted",
  "unread_count": 4
}
```

---

### 6. **Delete All Read Notifications**

**Endpoint:** `POST /notifications/delete-all-read/`

**Description:** Delete all read notifications

**Request Example:**
```bash
POST /notifications/delete-all-read/
Cookie: sessionid=your_session_id
X-CSRFToken: csrf_token_value
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "15 notifications deleted",
  "deleted_count": 15
}
```

---

### 7. **Notification Page (Web UI)**

**Endpoint:** `GET /notifications/`

**Description:** Full-featured notification page with filters and pagination

**Query Parameters:**
- `type` (string, default: "all") - Filter by notification type
- `status` (string, default: "all") - Filter by status (all/unread/read)
- `page` (int, default: 1) - Page number

**Request Example:**
```bash
GET /notifications/?type=ORDER&status=unread&page=1
Cookie: sessionid=your_session_id
```

**Response:** HTML page with notifications

---

## 🔄 WebSocket Connection

### Connection URL
```
ws://127.0.0.1:8000/ws/notifications/
```

For production with HTTPS:
```
wss://yourdomain.com/ws/notifications/
```

### Connection Flow

```
1. Client connects to WebSocket URL
2. Server authenticates user (via session cookie)
3. User joins their personal notification channel
4. Server sends initial unread count
5. Client receives real-time notifications
```

### Authentication

WebSocket uses Django session authentication. Pass session cookie in connection:

**JavaScript Example:**
```javascript
const ws = new WebSocket('ws://127.0.0.1:8000/ws/notifications/');
// Cookies are automatically included by browser
```

**Python Example:**
```python
import websockets
import asyncio

async def connect():
    uri = "ws://127.0.0.1:8000/ws/notifications/"
    headers = {
        "Cookie": f"sessionid={session_id}"
    }
    async with websockets.connect(uri, extra_headers=headers) as websocket:
        # Connected
        message = await websocket.recv()
        print(message)

asyncio.run(connect())
```

### Message Types

#### 1. **Server → Client: Unread Count**

Sent when:
- Connection established
- Count changes
- Client requests update

**Format:**
```json
{
  "type": "unread_count",
  "count": 5
}
```

#### 2. **Server → Client: New Notification**

Sent when:
- New notification created for user

**Format:**
```json
{
  "type": "notification",
  "notification": {
    "id": 123,
    "type": "ORDER",
    "title": "New Order",
    "message": "Order #1234 received",
    "link_url": "/orders/1234/",
    "link_text": "View Order",
    "is_read": false,
    "created_at": "2026-01-31 10:30:00"
  }
}
```

#### 3. **Client → Server: Request Count**

Client can request current unread count:

**Format:**
```json
{
  "type": "get_count"
}
```

#### 4. **Client → Server: Keep-Alive Ping**

Prevent connection timeout:

**Format:**
```json
{
  "type": "ping"
}
```

**Server Response:**
```json
{
  "type": "pong"
}
```

---

## 🔐 Authentication

The notification system supports two authentication methods:

### Method 1: Username/Password Authentication (Standard)

Uses Django's built-in session authentication.

**Step 1: Login**
```bash
POST /auth/login/
Content-Type: application/x-www-form-urlencoded

username=myuser&password=mypassword
```

**Step 2: Extract Session Cookie**
```
Response Headers:
Set-Cookie: sessionid=abc123xyz; Path=/; HttpOnly
```

**Step 3: Use Session Cookie**
All subsequent API and WebSocket requests must include this cookie:
```
Cookie: sessionid=abc123xyz
```

---

### Method 2: Passkey Authentication (API/Mobile Apps) ⭐ RECOMMENDED

**Recommended for third-party integrations and mobile apps** - simpler and faster authentication using a passkey.

**Endpoint:** `POST /api/passkey-auth`

**Description:** Authenticate using a passkey and receive session cookie

**Headers:**
- `Content-Type: application/json`
- **No CSRF token required** (endpoint is CSRF exempt)

**Request Body:**
```json
{
  "passkey": "11111"
}
```

**Available Passkeys:**
| Passkey | User ID | Description |
|---------|---------|-------------|
| `11111` | 1 | User 1 |
| `22222` | 2 | User 2 |
| `33333` | 3 | User 3 |
| `44444` | 4 | User 4 |
| `55555` | 5 | User 5 |

**Success Response (200 OK):**
```json
{
  "message": "Passkey authentication successful"
}
```

**Response Headers:**
```
Set-Cookie: sessionid=abc123xyz; Path=/; HttpOnly
```

**Error Response (400 Bad Request):**
```json
{
  "error": "Invalid passkey"
}
```

**Example - Python:**
```python
import requests

# Passkey authentication
url = "http://127.0.0.1:8000/api/passkey-auth"
data = {"passkey": "11111"}

response = requests.post(url, json=data)

if response.status_code == 200:
    print("Authenticated!")
    session_cookies = response.cookies
    
    # Use session for subsequent requests
    notifications = requests.get(
        "http://127.0.0.1:8000/notifications/api/",
        cookies=session_cookies
    )
    print(notifications.json())
else:
    print(f"Error: {response.json()['error']}")
```

**Example - JavaScript:**
```javascript
// Passkey authentication
fetch('http://127.0.0.1:8000/api/passkey-auth', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({ passkey: '11111' }),
    credentials: 'include'  // Important: include cookies
})
.then(response => response.json())
.then(data => {
    if (data.message) {
        console.log('Authenticated!');
        // Now fetch notifications
        return fetch('http://127.0.0.1:8000/notifications/api/', {
            credentials: 'include'
        });
    }
})
.then(response => response.json())
.then(notifications => {
    console.log('Notifications:', notifications);
});
```

**Example - cURL:**
```bash
# Authenticate with passkey
curl -X POST http://127.0.0.1:8000/api/passkey-auth \
  -H "Content-Type: application/json" \
  -d '{"passkey":"11111"}' \
  -c cookies.txt

# Use session cookie for notifications
curl http://127.0.0.1:8000/notifications/api/ \
  -b cookies.txt
```

**Why Use Passkey Auth?**
- ✅ No CSRF token required
- ✅ Simpler JSON payload (no form data)
- ✅ Faster for API/mobile integrations
- ✅ No username/password management
- ✅ Works great with WebSocket connections
- ✅ Perfect for third-party apps

---

### Authentication Comparison

| Feature | Username/Password | Passkey |
|---------|------------------|---------|
| Use Case | Web forms | APIs/Mobile apps |
| Format | Form data | JSON |
| CSRF Required | Yes | No |
| Session Cookie | Yes | Yes |
| WebSocket Support | Yes | Yes |
| Complexity | Medium | Low |
| Best For | Human users | Automated systems |

### CSRF Token (for POST requests)

Django requires CSRF token for POST/PUT/DELETE requests:

**Get CSRF Token:**
```javascript
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');
```

**Include in POST Request:**
```javascript
fetch('/notifications/123/mark-read/', {
    method: 'POST',
    headers: {
        'X-CSRFToken': csrftoken,
        'Content-Type': 'application/json'
    }
});
```

---

## 🌐 Third-Party Integration

### Scenario: External Service Integration

If you're building a third-party app/service that needs to access notifications:

### Step 1: Obtain API Credentials

**Option A: Use Passkey Authentication (⭐ Recommended for APIs)**
```python
import requests

# Passkey authentication - Simple and fast!
auth_url = "http://127.0.0.1:8000/api/passkey-auth"
passkey = "11111"  # Use your assigned passkey

response = requests.post(auth_url, json={"passkey": passkey})

if response.status_code == 200:
    session_cookies = response.cookies
    print(f"✓ Authenticated! Session ID: {session_cookies.get('sessionid')}")
else:
    print(f"✗ Error: {response.json()['error']}")
```

**Option B: Use Username/Password (Traditional)**
```python
import requests

# Login with username/password
login_url = "http://127.0.0.1:8000/auth/login/"
credentials = {
    "username": "your_username",
    "password": "your_password"
}

response = requests.post(login_url, data=credentials, allow_redirects=False)
session_cookies = response.cookies

# Store session cookies for future requests
print(f"Session ID: {session_cookies.get('sessionid')}")
```

### Step 3: Fetch Notifications via API

```python
# Get notifications
api_url = "http://127.0.0.1:8000/notifications/api/"
params = {
    "limit": 20,
    "offset": 0,
    "unread_only": "true"
}

response = requests.get(api_url, params=params, cookies=session_cookies)
data = response.json()

for notification in data['notifications']:
    print(f"[{notification['type']}] {notification['title']}")
    print(f"  Message: {notification['message']}")
    print(f"  Created: {notification['created_at']}")
    print()
```

### Step 4: Real-Time WebSocket Connection

```python
import asyncio
import websockets
import json

async def notification_listener():
    uri = "ws://127.0.0.1:8000/ws/notifications/"
    
    # Include session cookie
    headers = {
        "Cookie": f"sessionid={session_cookies.get('sessionid')}"
    }
    
    async with websockets.connect(uri, extra_headers=headers) as websocket:
        print("Connected to WebSocket")
        
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            if data['type'] == 'notification':
                notif = data['notification']
                print(f"NEW: [{notif['type']}] {notif['title']}")
            elif data['type'] == 'unread_count':
                print(f"Unread count: {data['count']}")

# Run listener
asyncio.run(notification_listener())
```

---

## 📱 Mobile App Integration

### React Native / Flutter / Native Apps

Mobile apps should use the REST API for data fetching and WebSocket for real-time updates.

### Architecture

```
Mobile App
    ├── Login Screen → Get Session Token
    ├── API Service → Fetch/Update Notifications
    ├── WebSocket Service → Real-Time Updates
    └── Local Notifications → OS Notifications
```

### Example: React Native

```javascript
// api.js - API Service
class NotificationAPI {
    constructor(sessionId) {
        this.sessionId = sessionId;
        this.baseUrl = 'http://your-server.com';
    }
    
    async getNotifications(limit = 20, offset = 0) {
        const response = await fetch(
            `${this.baseUrl}/notifications/api/?limit=${limit}&offset=${offset}`,
            {
                headers: {
                    'Cookie': `sessionid=${this.sessionId}`
                }
            }
        );
        return await response.json();
    }
    
    async markAsRead(notificationId) {
        const response = await fetch(
            `${this.baseUrl}/notifications/${notificationId}/mark-read/`,
            {
                method: 'POST',
                headers: {
                    'Cookie': `sessionid=${this.sessionId}`,
                    'X-CSRFToken': this.csrfToken
                }
            }
        );
        return await response.json();
    }
}

// websocket.js - WebSocket Service
class NotificationWebSocket {
    constructor(sessionId, onMessage) {
        this.sessionId = sessionId;
        this.onMessage = onMessage;
        this.ws = null;
    }
    
    connect() {
        this.ws = new WebSocket('ws://your-server.com/ws/notifications/');
        
        this.ws.onopen = () => {
            console.log('WebSocket Connected');
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.onMessage(data);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket Error:', error);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket Disconnected');
            // Reconnect after 5 seconds
            setTimeout(() => this.connect(), 5000);
        };
    }
    
    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Usage in React Native Component
import React, { useEffect, useState } from 'react';
import { View, Text, FlatList } from 'react-native';
import PushNotification from 'react-native-push-notification';

const NotificationScreen = ({ sessionId }) => {
    const [notifications, setNotifications] = useState([]);
    const [unreadCount, setUnreadCount] = useState(0);
    
    useEffect(() => {
        // Initialize API
        const api = new NotificationAPI(sessionId);
        
        // Fetch initial notifications
        api.getNotifications().then(data => {
            setNotifications(data.notifications);
            setUnreadCount(data.unread_count);
        });
        
        // Connect WebSocket
        const ws = new NotificationWebSocket(sessionId, (data) => {
            if (data.type === 'notification') {
                // Add new notification to list
                setNotifications(prev => [data.notification, ...prev]);
                setUnreadCount(prev => prev + 1);
                
                // Show OS notification
                PushNotification.localNotification({
                    title: data.notification.title,
                    message: data.notification.message,
                });
            } else if (data.type === 'unread_count') {
                setUnreadCount(data.count);
            }
        });
        
        ws.connect();
        
        return () => ws.disconnect();
    }, [sessionId]);
    
    return (
        <View>
            <Text>Unread: {unreadCount}</Text>
            <FlatList
                data={notifications}
                renderItem={({ item }) => (
                    <View>
                        <Text>{item.title}</Text>
                        <Text>{item.message}</Text>
                    </View>
                )}
            />
        </View>
    );
};
```

---

## 🌐 Standalone HTML Client

Complete standalone HTML file for testing/integration:

### File: `notification_client.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GST Billing - Notification Client</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: Arial, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        h1 {
            color: #333;
            margin-bottom: 20px;
        }
        
        .status {
            padding: 10px;
            margin-bottom: 20px;
            border-radius: 5px;
            font-weight: bold;
        }
        
        .status.disconnected {
            background: #ffebee;
            color: #c62828;
        }
        
        .status.connected {
            background: #e8f5e9;
            color: #2e7d32;
        }
        
        .login-form {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        input, button {
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }
        
        button {
            background: #2196f3;
            color: white;
            border: none;
            cursor: pointer;
        }
        
        button:hover {
            background: #1976d2;
        }
        
        .notification {
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            margin-bottom: 10px;
            background: white;
        }
        
        .notification.unread {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
        }
        
        .notification-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .notification-title {
            font-weight: bold;
            font-size: 16px;
        }
        
        .notification-badge {
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            color: white;
        }
        
        .badge-info { background: #2196f3; }
        .badge-success { background: #4caf50; }
        .badge-warning { background: #ff9800; }
        .badge-danger { background: #f44336; }
        
        .notification-message {
            color: #666;
            margin-bottom: 10px;
        }
        
        .notification-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: #999;
        }
        
        .notification-actions button {
            padding: 5px 10px;
            margin-left: 5px;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔔 Notification Client</h1>
        
        <div id="status" class="status disconnected">
            Status: Disconnected
        </div>
        
        <div id="loginSection" class="login-form">
            <input type="text" id="serverUrl" placeholder="Server URL" value="http://127.0.0.1:8000">
            
            <div style="margin: 10px 0; padding: 10px; background: #e3f2fd; border-radius: 5px;">
                <label style="display: block; margin-bottom: 5px;">
                    <input type="radio" name="authMethod" value="passkey" checked onchange="toggleAuthMethod()">
                    <strong>Passkey Auth (Recommended)</strong>
                </label>
                <label style="display: block;">
                    <input type="radio" name="authMethod" value="username" onchange="toggleAuthMethod()">
                    <strong>Username/Password Auth</strong>
                </label>
            </div>
            
            <div id="passkeyForm">
                <input type="text" id="passkey" placeholder="Passkey (e.g., 11111)" value="11111">
                <small style="color: #666; display: block; margin-top: 5px;">
                    Available: 11111, 22222, 33333, 44444, 55555
                </small>
            </div>
            
            <div id="usernameForm" style="display: none;">
                <input type="text" id="username" placeholder="Username">
                <input type="password" id="password" placeholder="Password">
            </div>
            
            <button onclick="login()">Login</button>
        </div>
        
        <div id="notificationSection" style="display: none;">
            <div style="margin-bottom: 20px;">
                <button onclick="refreshNotifications()">🔄 Refresh</button>
                <button onclick="markAllRead()">✓ Mark All Read</button>
                <span id="unreadCount" style="margin-left: 20px; font-weight: bold;">
                    Unread: 0
                </span>
            </div>
            
            <div id="notifications"></div>
        </div>
    </div>
    
    <script>
        let serverUrl = 'http://127.0.0.1:8000';
        let sessionId = null;
        let csrfToken = null;
        let ws = null;
        let notifications = [];
        
        function setStatus(text, connected) {
            const statusEl = document.getElementById('status');
            statusEl.textContent = 'Status: ' + text;
            statusEl.className = 'status ' + (connected ? 'connected' : 'disconnected');
        }
        
        function toggleAuthMethod() {
            const authMethod = document.querySelector('input[name="authMethod"]:checked').value;
            document.getElementById('passkeyForm').style.display = 
                authMethod === 'passkey' ? 'block' : 'none';
            document.getElementById('usernameForm').style.display = 
                authMethod === 'username' ? 'block' : 'none';
        }
        
        async function login() {
            serverUrl = document.getElementById('serverUrl').value;
            const authMethod = document.querySelector('input[name="authMethod"]:checked').value;
            
            try {
                let response;
                
                if (authMethod === 'passkey') {
                    // Passkey authentication (Recommended)
                    const passkey = document.getElementById('passkey').value;
                    
                    response = await fetch(`${serverUrl}/api/passkey-auth`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ passkey: passkey }),
                        credentials: 'include'
                    });
                    
                    const data = await response.json();
                    if (!data.message || response.status !== 200) {
                        alert(data.error || 'Passkey authentication failed');
                        return;
                    }
                } else {
                    // Username/Password authentication
                    const username = document.getElementById('username').value;
                    const password = document.getElementById('password').value;
                    
                    const formData = new URLSearchParams();
                    formData.append('username', username);
                    formData.append('password', password);
                    
                    response = await fetch(`${serverUrl}/auth/login/`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                        body: formData,
                        credentials: 'include',
                        redirect: 'manual'
                    });
                }
                
                // Extract cookies
                const cookies = document.cookie.split(';');
                for (let cookie of cookies) {
                    const [name, value] = cookie.trim().split('=');
                    if (name === 'sessionid') {
                        sessionId = value;
                    } else if (name === 'csrftoken') {
                        csrfToken = value;
                    }
                }
                
                if (sessionId) {
                    document.getElementById('loginSection').style.display = 'none';
                    document.getElementById('notificationSection').style.display = 'block';
                    setStatus('Connected', true);
                    
                    // Load notifications
                    await refreshNotifications();
                    
                    // Connect WebSocket
                    connectWebSocket();
                } else {
                    alert('Login failed - no session cookie received');
                }
            } catch (error) {
                console.error('Login error:', error);
                alert('Login error: ' + error.message);
            }
        }
                
                if (sessionId) {
                    document.getElementById('loginSection').style.display = 'none';
                    document.getElementById('notificationSection').style.display = 'block';
                    setStatus('Connected', true);
                    
                    // Load notifications
                    await refreshNotifications();
                    
                    // Connect WebSocket
                    connectWebSocket();
                } else {
                    alert('Login failed');
                }
            } catch (error) {
                console.error('Login error:', error);
                alert('Login error: ' + error.message);
            }
        }
        
        async function refreshNotifications() {
            try {
                const response = await fetch(
                    `${serverUrl}/notifications/api/?limit=50&offset=0`,
                    { credentials: 'include' }
                );
                
                const data = await response.json();
                notifications = data.notifications;
                updateUnreadCount(data.unread_count);
                renderNotifications();
            } catch (error) {
                console.error('Fetch error:', error);
            }
        }
        
        function renderNotifications() {
            const container = document.getElementById('notifications');
            container.innerHTML = '';
            
            if (notifications.length === 0) {
                container.innerHTML = '<p style="text-align: center; color: #999; padding: 40px;">No notifications</p>';
                return;
            }
            
            notifications.forEach(notif => {
                const div = document.createElement('div');
                div.className = 'notification' + (notif.is_read ? '' : ' unread');
                div.innerHTML = `
                    <div class="notification-header">
                        <div class="notification-title">${notif.title}</div>
                        <span class="notification-badge badge-${getBadgeClass(notif.type)}">
                            ${notif.type}
                        </span>
                    </div>
                    <div class="notification-message">${notif.message}</div>
                    <div class="notification-footer">
                        <span>📅 ${notif.created_at}</span>
                        <div class="notification-actions">
                            ${notif.link_url ? 
                                `<button onclick="openLink('${notif.link_url}')">🔗 ${notif.link_text || 'View'}</button>` 
                                : ''}
                            ${!notif.is_read ? 
                                `<button onclick="markAsRead(${notif.id})">✓ Read</button>` 
                                : ''}
                            <button onclick="deleteNotification(${notif.id})">🗑 Delete</button>
                        </div>
                    </div>
                `;
                container.appendChild(div);
            });
        }
        
        function getBadgeClass(type) {
            const map = {
                'INFO': 'info',
                'SUCCESS': 'success',
                'WARNING': 'warning',
                'ERROR': 'danger',
                'ORDER': 'info',
                'INVOICE': 'info',
                'PAYMENT': 'success'
            };
            return map[type] || 'info';
        }
        
        async function markAsRead(id) {
            try {
                await fetch(`${serverUrl}/notifications/${id}/mark-read/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    credentials: 'include'
                });
                
                // Update local data
                const notif = notifications.find(n => n.id === id);
                if (notif) notif.is_read = true;
                renderNotifications();
            } catch (error) {
                console.error('Mark as read error:', error);
            }
        }
        
        async function markAllRead() {
            try {
                await fetch(`${serverUrl}/notifications/mark-all-read/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    credentials: 'include'
                });
                
                notifications.forEach(n => n.is_read = true);
                updateUnreadCount(0);
                renderNotifications();
            } catch (error) {
                console.error('Mark all read error:', error);
            }
        }
        
        async function deleteNotification(id) {
            try {
                await fetch(`${serverUrl}/notifications/${id}/delete/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    credentials: 'include'
                });
                
                notifications = notifications.filter(n => n.id !== id);
                renderNotifications();
            } catch (error) {
                console.error('Delete error:', error);
            }
        }
        
        function openLink(url) {
            window.open(serverUrl + url, '_blank');
        }
        
        function updateUnreadCount(count) {
            document.getElementById('unreadCount').textContent = `Unread: ${count}`;
        }
        
        function connectWebSocket() {
            const wsUrl = serverUrl.replace('http://', 'ws://').replace('https://', 'wss://');
            ws = new WebSocket(`${wsUrl}/ws/notifications/`);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                setStatus('Connected (Live)', true);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                
                if (data.type === 'notification') {
                    // New notification received
                    notifications.unshift(data.notification);
                    renderNotifications();
                    
                    // Show browser notification
                    if (Notification.permission === 'granted') {
                        new Notification(data.notification.title, {
                            body: data.notification.message,
                            icon: '/favicon.ico'
                        });
                    }
                } else if (data.type === 'unread_count') {
                    updateUnreadCount(data.count);
                }
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                setStatus('WebSocket Error', false);
            };
            
            ws.onclose = () => {
                console.log('WebSocket closed');
                setStatus('Disconnected', false);
                // Reconnect after 5 seconds
                setTimeout(connectWebSocket, 5000);
            };
        }
        
        // Request browser notification permission
        if (Notification.permission === 'default') {
            Notification.requestPermission();
        }
    </script>
</body>
</html>
```

**Save this file and open in browser to test the notification system!**

---

## 💻 Desktop App Integration

### Python Tkinter Desktop App

See `notification_desktop_app.py` for complete implementation.

**Key Features:**
- Auto-login with saved credentials
- Real-time WebSocket notifications
- Windows toast notifications (winotify)
- Full CRUD operations
- Filters and pagination

**Installation:**
```bash
pip install winotify websockets requests
```

**Usage:**
```bash
python notification_desktop_app.py
```

---

## 📝 Code Examples

### Creating Notifications (Server-Side)

```python
from gstbillingapp.utils import create_notification

# Simple notification
create_notification(
    user=request.user,
    title="Welcome!",
    message="Welcome to GST Billing System",
    notification_type="SUCCESS"
)

# Notification with link
create_notification(
    user=customer_user,
    title="New Order Received",
    message=f"Order #{order.id} has been placed successfully",
    notification_type="ORDER",
    link_url=f"/mobile_v1/customer/orders/{order.id}/",
    link_text="View Order"
)

# Notification with related object
create_notification(
    user=admin_user,
    title="Payment Received",
    message=f"₹{amount} received from {customer.name}",
    notification_type="PAYMENT",
    link_url=f"/customers/{customer.id}/",
    link_text="View Customer",
    related_object_type="Customer",
    related_object_id=customer.id
)
```

### Bulk Send Notifications

```python
from django.contrib.auth.models import User
from gstbillingapp.utils import create_notification

# Notify all admins
admin_users = User.objects.filter(is_staff=True)
for admin in admin_users:
    create_notification(
        user=admin,
        title="System Maintenance",
        message="System will be down for maintenance on Saturday 2AM-4AM",
        notification_type="SYSTEM"
    )

# Notify specific users
user_ids = [1, 2, 3, 4, 5]
users = User.objects.filter(id__in=user_ids)
for user in users:
    create_notification(
        user=user,
        title="Special Offer",
        message="Get 20% off on all products this week!",
        notification_type="INFO"
    )
```

---

## 🚀 Production Deployment

### Using Redis for WebSocket (Recommended)

**1. Install Redis:**
```bash
# Windows: Download from https://github.com/microsoftarchive/redis/releases
# Linux: sudo apt-get install redis-server
# Mac: brew install redis

pip install channels-redis
```

**2. Update settings.py:**
```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('127.0.0.1', 6379)],
        },
    },
}
```

**3. Start Redis:**
```bash
redis-server
```

**4. Run Django with Daphne:**
```bash
daphne -b 0.0.0.0 -p 8000 gstbilling.asgi:application
```

---

## 🔧 Troubleshooting

### Common Issues

**1. WebSocket Connection Failed**
- Check if Daphne is running (not runserver)
- Verify session cookie is included
- Check firewall/proxy settings

**2. CORS Issues**
- Add CORS headers if accessing from different domain
- Install: `pip install django-cors-headers`

**3. Authentication Failed**
- Ensure session cookie is valid
- Check if user is authenticated
- Verify cookie domain matches

**4. Notifications Not Updating**
- Check Redis connection
- Verify WebSocket is connected
- Check browser console for errors

---

## 📞 Support

For issues or questions:
1. Check server logs: `python manage.py runserver` output
2. Check browser console for JavaScript errors
3. Test WebSocket connection manually
4. Verify authentication is working

---

## 🎯 Quick Start Checklist

- [ ] Server running on http://127.0.0.1:8000
- [ ] User account created
- [ ] Login successful (session cookie obtained)
- [ ] API endpoints accessible
- [ ] WebSocket connection established
- [ ] Real-time notifications working
- [ ] Desktop app tested (optional)
- [ ] Standalone HTML client tested (optional)

---

**End of Guide**

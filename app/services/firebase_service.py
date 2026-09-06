import os
import json
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase Admin SDK
_firebase_initialized = False

def init_firebase():
    global _firebase_initialized
    if not _firebase_initialized:
        try:
            # 1. First check if JSON is provided in environment variables (ideal for Cloud Run / Production)
            env_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            if env_json:
                cert_dict = json.loads(env_json)
                cred = credentials.Certificate(cert_dict)
                firebase_admin.initialize_app(cred)
                _firebase_initialized = True
                print("Firebase Admin SDK initialized successfully from environment variable.")
                return

            # 2. Otherwise fall back to local serviceAccountKey.json file
            cred_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "serviceAccountKey.json")
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                _firebase_initialized = True
                print("Firebase Admin SDK initialized successfully from file.")
            else:
                print(f"Firebase Admin SDK not initialized: Neither FIREBASE_SERVICE_ACCOUNT_JSON nor {cred_path} found.")
        except Exception as e:
            print(f"Error initializing Firebase Admin SDK: {e}")

def send_push_notification(fcm_token: str, title: str, body: str, data: dict = None):
    """
    Sends a push notification to a specific FCM token.
    """
    if not _firebase_initialized:
        init_firebase()
        if not _firebase_initialized:
            print("Cannot send push notification: Firebase not initialized.")
            return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=fcm_token,
        )

        response = messaging.send(message)
        print(f"Successfully sent message: {response}")
        return True
    except Exception as e:
        print(f"Error sending push notification: {e}")
        return False

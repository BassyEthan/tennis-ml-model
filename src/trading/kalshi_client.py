"""
Kalshi API client for trading tennis predictions.
Based on Kalshi's official starter code structure.
Handles authentication, signing, and API requests.
"""

import os
import base64
import requests
import time
from pathlib import Path
from typing import Dict, Optional, Any
from enum import Enum
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


class Environment(Enum):
    """Kalshi API environment."""
    DEMO = "demo"
    PROD = "prod"


class KalshiBaseClient:
    """Base client class for interacting with the Kalshi API."""
    
    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.PROD,
    ):
        """
        Initializes the client with the provided API key and private key.

        Args:
            key_id: Your Kalshi API key ID (access key).
            private_key: Your RSA private key.
            environment: The API environment to use (DEMO or PROD).
        """
        self.key_id = key_id
        self.private_key = private_key
        self.environment = environment
        
        if self.environment == Environment.DEMO:
            self.HTTP_BASE_URL = "https://demo-api.kalshi.co"
            self.WS_BASE_URL = "wss://demo-api.kalshi.co"
        elif self.environment == Environment.PROD:
            self.HTTP_BASE_URL = "https://api.elections.kalshi.com"
            self.WS_BASE_URL = "wss://api.elections.kalshi.com"
        else:
            raise ValueError("Invalid environment")
    
    def request_headers(self, method: str, path: str) -> Dict[str, Any]:
        """
        Generates the required authentication headers for API requests.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (without query parameters for signing)
            
        Returns:
            Dictionary of headers
        """
        current_time_milliseconds = int(time.time() * 1000)
        timestamp_str = str(current_time_milliseconds)
        
        # Remove query params from path for signing
        path_parts = path.split('?')
        path_without_query = path_parts[0]
        
        msg_string = timestamp_str + method + path_without_query
        signature = self.sign_pss_text(msg_string)
        
        headers = {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
        }
        return headers
    
    def sign_pss_text(self, text: str) -> str:
        """
        Signs the text using RSA-PSS and returns the base64 encoded signature.
        
        Args:
            text: Text to sign
            
        Returns:
            Base64-encoded signature
        """
        message = text.encode('utf-8')
        try:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode('utf-8')
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e


class KalshiHttpClient(KalshiBaseClient):
    """Client for handling HTTP connections to the Kalshi API."""
    
    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.PROD,
    ):
        super().__init__(key_id, private_key, environment)
        self.host = self.HTTP_BASE_URL
        self.exchange_url = "/trade-api/v2/exchange"
        self.markets_url = "/trade-api/v2/markets"
        self.portfolio_url = "/trade-api/v2/portfolio"
        self.last_api_call = datetime.now()
    
    def rate_limit(self) -> None:
        """Built-in rate limiter to prevent exceeding API rate limits."""
        THRESHOLD_IN_MILLISECONDS = 100
        now = datetime.now()
        threshold_in_microseconds = 1000 * THRESHOLD_IN_MILLISECONDS
        threshold_in_seconds = THRESHOLD_IN_MILLISECONDS / 1000
        if now - self.last_api_call < timedelta(microseconds=threshold_in_microseconds):
            time.sleep(threshold_in_seconds)
        self.last_api_call = datetime.now()
    
    def raise_if_bad_response(self, response: requests.Response) -> None:
        """Raises an HTTPError if the response status code indicates an error."""
        if response.status_code not in range(200, 299):
            response.raise_for_status()
    
    def post(self, path: str, body: dict) -> Any:
        """Performs an authenticated POST request to the Kalshi API."""
        self.rate_limit()
        response = requests.post(
            self.host + path,
            json=body,
            headers=self.request_headers("POST", path),
            timeout=10
        )
        self.raise_if_bad_response(response)
        return response.json()
    
    def get(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated GET request to the Kalshi API."""
        self.rate_limit()
        
        # Build full path with query params for signing
        full_path = path
        if params:
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            full_path = f"{path}?{query_string}"
        
        response = requests.get(
            self.host + path,
            headers=self.request_headers("GET", full_path),
            params=params,
            timeout=10
        )
        self.raise_if_bad_response(response)
        return response.json()
    
    def delete(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated DELETE request to the Kalshi API."""
        self.rate_limit()
        
        # Build full path with query params for signing
        full_path = path
        if params:
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            full_path = f"{path}?{query_string}"
        
        response = requests.delete(
            self.host + path,
            headers=self.request_headers("DELETE", full_path),
            params=params,
            timeout=10
        )
        self.raise_if_bad_response(response)
        return response.json()
    
    def get_balance(self) -> Dict[str, Any]:
        """Retrieves the account balance."""
        return self.get(self.portfolio_url + '/balance')
    
    def get_exchange_status(self) -> Dict[str, Any]:
        """Retrieves the exchange status."""
        return self.get(self.exchange_url + "/status")
    
    def get_events(
        self,
        search: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get events from Kalshi API.
        
        Args:
            search: Search keyword (e.g., "tennis")
            status: Filter by status (e.g., "open")
            limit: Maximum number of results
            cursor: Pagination cursor
        """
        params = {}
        if search:
            params['search'] = search
        if status:
            params['status'] = status
        if limit:
            params['limit'] = min(limit, 1000)
        if cursor:
            params['cursor'] = cursor
        
        # Try v1/events first, fallback to v2 if needed
        try:
            return self.get("/trade-api/v1/events", params=params)
        except Exception:
            # Fallback to v2 if v1 doesn't exist
            return self.get("/trade-api/v2/events", params=params)
    
    def get_markets(
        self,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves markets based on provided filters.
        
        Args:
            event_ticker: Filter by event ticker
            series_ticker: Filter by series ticker (e.g., "KXATPMATCH", "KXUNITEDCUPMATCH") - ATP only
            limit: Maximum number of results (max ~1000)
            status: Filter by market status (e.g., "open", "closed")
            cursor: Pagination cursor from previous response
        """
        params = {}
        if event_ticker:
            params['event_ticker'] = event_ticker
        if series_ticker:
            params['series_ticker'] = series_ticker
        if limit:
            params['limit'] = min(limit, 1000)  # Cap at 1000
        if status:
            params['status'] = status
        if cursor:
            params['cursor'] = cursor
        
        return self.get(self.markets_url, params=params)
    
    def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        """
        Get orderbook for a specific market.
        
        Args:
            ticker: Market ticker symbol
        """
        return self.get(f"/trade-api/v2/markets/{ticker}/orderbook")
    
    def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price: Optional[int] = None,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Place an order on Kalshi.
        
        Args:
            ticker: Market ticker symbol
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price: Price in cents (optional for market orders)
            client_order_id: Optional client order ID
        """
        order_data = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count
        }
        
        if price is not None:
            order_data["price"] = price
        
        if client_order_id:
            order_data["client_order_id"] = client_order_id
        
        return self.post(self.portfolio_url + "/orders", order_data)
    
    def get_orders(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get order history.
        
        Args:
            status: Filter by status (e.g., "resting", "executed", "cancelled")
            limit: Maximum number of results
        """
        params = {}
        if status:
            params['status'] = status
        if limit:
            params['limit'] = limit
        
        return self.get(self.portfolio_url + "/orders", params=params)
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
        """
        return self.delete(f"{self.portfolio_url}/orders/{order_id}")
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions."""
        return self.get(self.portfolio_url + "/positions")


# Backward compatibility alias - maps to KalshiHttpClient
class KalshiClient(KalshiHttpClient):
    """
    Alias for KalshiHttpClient for backward compatibility.
    Automatically loads credentials from environment/config.
    """
    
    def __init__(
        self,
        access_key: Optional[str] = None,
        private_key: Optional[rsa.RSAPrivateKey] = None,
        private_key_path: Optional[str] = None,
        base_url: Optional[str] = None,
        environment: Optional[Environment] = None,
    ):
        """
        Initialize Kalshi client with automatic credential loading.
        
        Args:
            access_key: Kalshi access key (or from environment)
            private_key: Private key as RSA object (or will load from file/string)
            private_key_path: Path to private key file (or from environment)
            base_url: API base URL (deprecated - use environment instead)
            environment: Environment enum (DEMO or PROD)
        """
        from config.settings import (
            KALSHI_ACCESS_KEY,
            KALSHI_PRIVATE_KEY,
            KALSHI_PRIVATE_KEY_PATH,
            KALSHI_USE_PRODUCTION,
        )
        
        # Determine environment
        if environment is None:
            if base_url:
                # Infer from base_url if provided
                if "demo-api" in base_url:
                    env = Environment.DEMO
                else:
                    env = Environment.PROD
            else:
                # Use config setting
                env = Environment.PROD if KALSHI_USE_PRODUCTION else Environment.DEMO
        else:
            env = environment
        
        # Get key_id (access_key)
        key_id = access_key or KALSHI_ACCESS_KEY
        if not key_id:
            raise ValueError("KALSHI_ACCESS_KEY not provided")
        
        # Load private key
        if private_key:
            priv_key = private_key
        else:
            priv_key = self._load_private_key(private_key_path)
        
        # Initialize parent class
        super().__init__(key_id, priv_key, env)
    
    def _load_private_key(self, private_key_path: Optional[str] = None) -> rsa.RSAPrivateKey:
        """Load private key from file or string."""
        from config.settings import KALSHI_PRIVATE_KEY, KALSHI_PRIVATE_KEY_PATH
        
        # Try file first
        key_path = Path(private_key_path or KALSHI_PRIVATE_KEY_PATH)
        if key_path.exists():
            try:
                with open(key_path, "rb") as key_file:
                    return serialization.load_pem_private_key(
                        key_file.read(),
                        password=None,
                        backend=default_backend()
                    )
            except Exception as e:
                raise ValueError(f"Failed to load private key from file: {e}")
        
        # Fallback to string
        private_key_string = KALSHI_PRIVATE_KEY
        if private_key_string:
            try:
                key_bytes = private_key_string.encode('utf-8')
                if not private_key_string.strip().startswith('-----BEGIN'):
                    key_bytes = f"-----BEGIN PRIVATE KEY-----\n{private_key_string}\n-----END PRIVATE KEY-----".encode('utf-8')
                return serialization.load_pem_private_key(
                    key_bytes,
                    password=None,
                    backend=default_backend()
                )
            except Exception as e:
                raise ValueError(f"Failed to load private key from string: {e}")
        
        raise FileNotFoundError(
            f"Kalshi private key not found. "
            f"Please set KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY in environment/config."
        )

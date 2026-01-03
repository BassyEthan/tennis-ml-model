"""
Kalshi API client for trading tennis predictions.
Handles authentication, signing, and API requests.
"""

import os
import base64
import requests
import datetime
from pathlib import Path
from typing import Dict, Optional, Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


class KalshiClient:
    """Client for interacting with Kalshi prediction market API."""
    
    def __init__(self, access_key: Optional[str] = None, 
                 private_key: Optional[str] = None,
                 private_key_path: Optional[str] = None,
                 base_url: Optional[str] = None):
        """
        Initialize Kalshi client.
        
        Args:
            access_key: Kalshi access key (or from environment)
            private_key: Private key as string (or from KALSHI_PRIVATE_KEY env var)
            private_key_path: Path to private key file (or from environment)
            base_url: API base URL (or from environment)
        """
        from config.settings import (
            KALSHI_ACCESS_KEY, 
            KALSHI_PRIVATE_KEY,
            KALSHI_PRIVATE_KEY_PATH, 
            KALSHI_BASE_URL
        )
        
        self.access_key = access_key or KALSHI_ACCESS_KEY
        self.base_url = base_url or KALSHI_BASE_URL
        
        if not self.access_key:
            raise ValueError("KALSHI_ACCESS_KEY not provided")
        
        # Try to load from file first (as per Kalshi docs), then fallback to string
        self.private_key_path = Path(private_key_path or KALSHI_PRIVATE_KEY_PATH)
        
        if self.private_key_path.exists():
            # Load from file (preferred method, matches Kalshi docs)
            self.private_key = self._load_private_key_from_file()
        else:
            # Fallback: try loading from string if file doesn't exist
            private_key_string = private_key or KALSHI_PRIVATE_KEY
            if private_key_string:
                self.private_key = self._load_private_key_from_string(private_key_string)
            else:
                raise FileNotFoundError(
                    f"Kalshi private key file not found at {self.private_key_path}. "
                    f"Please place your private key file there (e.g., 'kalshi-key-2.key' or 'kalshi_private_key.pem'). "
                    f"Or set KALSHI_PRIVATE_KEY_PATH to point to your key file location."
                )
    
    def _load_private_key_from_string(self, key_string: str) -> rsa.RSAPrivateKey:
        """Load private key from string."""
        try:
            # Handle both with and without newlines
            key_bytes = key_string.encode('utf-8')
            
            # If it doesn't have proper PEM headers, try to add them
            if not key_string.strip().startswith('-----BEGIN'):
                # Assume it's just the key content, wrap it
                key_bytes = f"-----BEGIN PRIVATE KEY-----\n{key_string}\n-----END PRIVATE KEY-----".encode('utf-8')
            
            private_key = serialization.load_pem_private_key(
                key_bytes,
                password=None,  # Set password if key is encrypted
                backend=default_backend()
            )
            return private_key
        except Exception as e:
            raise ValueError(f"Failed to load private key from string: {e}")
    
    def _load_private_key_from_file(self) -> rsa.RSAPrivateKey:
        """Load private key from file."""
        try:
            with open(self.private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,  # Set password if key is encrypted
                    backend=default_backend()
                )
            return private_key
        except Exception as e:
            raise ValueError(f"Failed to load private key from file: {e}")
    
    def _sign_pss_text(self, text: str) -> str:
        """
        Sign text with private key using PSS padding.
        
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
    
    def _get_headers(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate authenticated headers for Kalshi API request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (without query parameters for signing)
            
        Returns:
            Dictionary of headers
        """
        # Get current timestamp in milliseconds
        current_time = datetime.datetime.now()
        timestamp_ms = int(current_time.timestamp() * 1000)
        timestamp_str = str(timestamp_ms)
        
        # Strip query parameters from path before signing
        path_without_query = path.split('?')[0]
        
        # Create message string: timestamp + method + path
        msg_string = timestamp_str + method + path_without_query
        
        # Sign the message
        signature = self._sign_pss_text(msg_string)
        
        return {
            'KALSHI-ACCESS-KEY': self.access_key,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp_str,
            'Content-Type': 'application/json'
        }
    
    def _request(self, method: str, path: str, data: Optional[Dict] = None, 
                params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make authenticated request to Kalshi API.
        
        Args:
            method: HTTP method
            path: API path
            data: Request body data (for POST/PUT)
            params: Query parameters
            
        Returns:
            JSON response as dictionary
        """
        url = self.base_url + path
        
        # Build full path with query params for signing
        full_path = path
        if params:
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            full_path = f"{path}?{query_string}"
        
        headers = self._get_headers(method, full_path)
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data, params=params, timeout=10)
            elif method == "PUT":
                response = requests.put(url, headers=headers, json=data, params=params, timeout=10)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, params=params, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Kalshi API request failed: {e}")
    
    def get_portfolio_balance(self) -> Dict[str, Any]:
        """Get current portfolio balance."""
        return self._request("GET", "/trade-api/v2/portfolio/balance")
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions."""
        return self._request("GET", "/trade-api/v2/portfolio/positions")
    
    def get_markets(self, event_ticker: Optional[str] = None, 
                   series_ticker: Optional[str] = None,
                   limit: int = 100) -> Dict[str, Any]:
        """
        Get available markets.
        
        Args:
            event_ticker: Filter by event ticker
            series_ticker: Filter by series ticker
            limit: Maximum number of results
        """
        params = {"limit": limit}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        
        return self._request("GET", "/trade-api/v2/markets", params=params)
    
    def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        """
        Get orderbook for a specific market.
        
        Args:
            ticker: Market ticker symbol
        """
        return self._request("GET", f"/trade-api/v2/markets/{ticker}/orderbook")
    
    def place_order(self, ticker: str, side: str, action: str, 
                   count: int, price: Optional[int] = None,
                   client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Place an order on Kalshi.
        
        Args:
            ticker: Market ticker symbol
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price: Price in cents (optional for market orders)
            client_order_id: Optional client order ID
            
        Returns:
            Order response
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
        
        return self._request("POST", "/trade-api/v2/portfolio/orders", data=order_data)
    
    def get_orders(self, status: Optional[str] = None,
                  limit: int = 100) -> Dict[str, Any]:
        """
        Get order history.
        
        Args:
            status: Filter by status (e.g., "resting", "executed", "cancelled")
            limit: Maximum number of results
        """
        params = {"limit": limit}
        if status:
            params["status"] = status
        
        return self._request("GET", "/trade-api/v2/portfolio/orders", params=params)
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
        """
        return self._request("DELETE", f"/trade-api/v2/portfolio/orders/{order_id}")


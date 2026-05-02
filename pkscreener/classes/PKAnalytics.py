#!/usr/bin/python3
"""
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""

import os
import sys
import threading
import time
import platform
import getpass
import json
import hashlib
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from PKDevTools.classes.Fetcher import fetcher
from PKDevTools.classes.Utils import random_user_agent
from PKDevTools.classes.Singleton import SingletonType, SingletonMixin
from PKDevTools.classes.pubsub.publisher import PKUserService
from pkscreener.classes import VERSION
from pkscreener.classes.ConfigManager import tools, parser


class AnalyticsCategory:
    """Constants for Google Analytics event categories."""
    APP = "App"
    USER = "User"
    SCAN = "Scan"
    SCREENING = "Screening"
    PERFORMANCE = "Performance"
    ERROR = "Error"
    FEATURE = "Feature"
    SUBSCRIPTION = "Subscription"
    DATA = "Data"
    SYSTEM = "System"


class AnalyticsAction:
    """Constants for Google Analytics event actions."""
    # App actions
    START = "start"
    EXIT = "exit"
    CRASH = "crash"
    
    # User actions
    LOGIN = "login"
    LOGOUT = "logout"
    REGISTER = "register"
    
    # Scan actions
    REQUEST = "request"
    COMPLETE = "complete"
    RESULT = "result"
    
    # Screening actions
    SCREEN = "screen"
    FILTER = "filter"
    SORT = "sort"
    
    # Performance actions
    LOAD_TIME = "load_time"
    RESPONSE_TIME = "response_time"
    MEMORY_USAGE = "memory_usage"
    
    # Feature actions
    USE = "use"
    CLICK = "click"
    NAVIGATE = "navigate"
    
    # Subscription actions  
    PURCHASE = "purchase"
    RENEW = "renew"
    CANCEL = "cancel"
    
    # Data actions
    DOWNLOAD = "download"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"


class AnalyticsLabel:
    """Constants for Google Analytics event labels."""
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class PKAnalyticsService(SingletonMixin, metaclass=SingletonType):
    """
    Analytics service for collecting anonymous usage metrics with GA4-style categorization.
    
    This service collects non-identifiable information with proper categorization
    for dashboard visualization. All collection is done in non-blocking background
    threads to avoid impacting user experience.
    
    Event Structure (GA4 compatible):
    ---------------------------------
    - Category: High-level grouping (App, User, Scan, Performance, etc.)
    - Action: The specific interaction (start, complete, click, etc.)
    - Label: Additional context (success, failure, info)
    - Value: Numeric value (optional, for metrics)
    - Custom Dimensions: Additional attributes for filtering
    
    Dashboard Categories:
    ---------------------
    1. App Usage - App starts, exits, session duration
    2. User Activity - Logins, registrations, user types
    3. Scanner Usage - Most used scanners, result counts
    4. Performance - Load times, response times, cache hit rates
    5. Feature Adoption - Feature usage frequency
    6. Errors - Error types and frequencies
    7. Subscription - Premium feature usage
    8. System - OS, platform, version distribution
    """
    
    def __init__(self):
        super(PKAnalyticsService, self).__init__()
        self.locationInfo = {}
        self.os = platform.system()
        self.os_version = platform.release()
        self.app_version = VERSION
        self.start_time = time.time()
        self.isRunner = "RUNNER" in os.environ.keys()
        self.onefile = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
        self.username = self._get_anonymous_id()  # Use anonymous ID instead of username
        self.configManager = tools()
        self.configManager.getConfig(parser)
        
        # Session tracking
        self.session_id = str(uuid.uuid4())
        self._session_start_time = time.time()
        
        # Feature usage counters (for aggregated reporting)
        self._feature_usage = {}
        
        # Non-blocking infrastructure
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analytics")
        self._location_lock = threading.Lock()
        self._location_fetched = False
        self._pending_events = []
        
        # Start background location fetch immediately (non-blocking)
        self._fetch_location_async()
        
        # Send session start event
        self.send_event(
            AnalyticsCategory.APP,
            AnalyticsAction.START,
            AnalyticsLabel.INFO,
            value=1
        )

    def _get_anonymous_id(self):
        """
        Generate a persistent anonymous user ID (no PII).
        
        Creates a hash based on system characteristics without storing
        personally identifiable information.
        
        Returns:
            str: Anonymized user identifier
        """
        try:
            # Use system characteristics (non-identifiable individually)
            system_info = f"{platform.system()}_{platform.machine()}_{os.getenv('USER', 'unknown')}"
            # Hash to create anonymous ID
            anonymous_id = hashlib.sha256(system_info.encode()).hexdigest()[:16]
            return f"user_{anonymous_id}"
        except Exception:
            return f"user_{uuid.uuid4().hex[:16]}"

    def _fetch_location_async(self):
        """Fetch location information in background thread (non-blocking)."""
        def fetch():
            try:
                if not self.configManager.enableUsageAnalytics:
                    return
                
                url = 'http://ipinfo.io/json'
                f = fetcher()
                response = f.fetchURL(url=url, timeout=5, headers={'user-agent': f'{random_user_agent()}'})
                
                if response and response.status_code == 200:
                    data = json.loads(response.text)
                    with self._location_lock:
                        self.locationInfo = data
                        self._location_fetched = True
                else:
                    with self._location_lock:
                        self.locationInfo = {"country": "Unknown", "region": "Unknown"}
                        self._location_fetched = True
                
                if self._pending_events:
                    for event in self._pending_events:
                        self._send_event_sync(**event)
                    self._pending_events.clear()
                    
            except Exception:
                with self._location_lock:
                    self.locationInfo = {"country": "Unknown", "region": "Unknown"}
                    self._location_fetched = True
                if self._pending_events:
                    for event in self._pending_events:
                        self._send_event_sync(**event)
                    self._pending_events.clear()
        
        threading.Thread(target=fetch, daemon=True, name="LocationFetcher").start()

    def send_event(self, category=None, action=None, label=None, value=None, 
               custom_dimensions=None, async_mode=True, 
               event_name=None, params=None):
        """
        Send a categorized analytics event (GA4 style) with backward compatibility.
        
        Supports three calling patterns:
        1. New style: send_event("System", "ping", "info")
        2. Dict style: send_event(event_name="app_start", params={"key": "value"})
        3. Mixed style: send_event("System", "ping", custom_dimensions={"key": "value"})
        
        Args:
            category (str): Event category (App, User, Scan, Performance, Error, System)
            action (str): Event action (start, complete, click, error, ping)
            label (str, optional): Event label (success, failure, info)
            value (int, optional): Numeric value for metrics
            custom_dimensions (dict, optional): Additional custom dimensions
            async_mode (bool): If True, send asynchronously
            event_name (str, optional): Alternative to action (for backward compatibility)
            params (dict, optional): Legacy parameters (for backward compatibility)
        """
        if not self.configManager.enableUsageAnalytics:
            return
        
        # Handle legacy call signature (from ping decorator)
        if category is not None and action is None and event_name is None:
            # Check if this is the old style with event_name as first arg
            if isinstance(category, str) and params is None:
                # send_event("ping") - just event name
                event_name = category
                category = AnalyticsCategory.SYSTEM
                action = event_name
                label = AnalyticsLabel.INFO
            elif isinstance(category, str) and isinstance(action, dict):
                # send_event("app_start", {"key": "value"})
                event_name = category
                params = action
                category = AnalyticsCategory.SYSTEM
                action = event_name
                label = params.get("label", AnalyticsLabel.INFO)
                value = params.get("value", None)
                custom_dimensions = params.get("custom_dimensions", {})
        
        # Handle event_name style
        if event_name is not None and category is None:
            category = AnalyticsCategory.SYSTEM
            action = event_name
            label = AnalyticsLabel.INFO
        
        # Ensure we have required fields
        if category is None:
            category = AnalyticsCategory.SYSTEM
        if action is None:
            action = "unknown"
        if label is None:
            label = AnalyticsLabel.INFO
        
        event_data = {
            "category": category,
            "action": action,
            "label": label,
            "value": value,
            "custom_dimensions": custom_dimensions or {}
        }
        
        if async_mode:
            self._executor.submit(self._send_event_sync, **event_data)
        else:
            self._send_event_sync(**event_data)

    def _send_event_sync(self, category, action, label=None, value=None, custom_dimensions=None):
        """
        Synchronous event sending (runs in background thread).
        """
        try:
            # Wait for location if needed
            if not self._location_fetched:
                wait_count = 0
                while not self._location_fetched and wait_count < 50:
                    time.sleep(0.01)
                    wait_count += 1
            
            with self._location_lock:
                current_location = self.locationInfo.copy() if self.locationInfo else {}
            
            # Build event parameters (GA4 structure)
            event_params = {
                # Required GA4 fields
                "event_category": category,
                "event_action": action,
                
                # Session information
                "app_session_id": self.session_id,
                "session_duration": round(time.time() - self._session_start_time, 1),
                
                # User information (anonymized)
                "user_id": self.username,
                "user_type": "premium" if self._is_premium_user() else "free",
                
                # System information
                "os": self.os,
                "os_version": self.os_version,
                "app_version": self.app_version,
                "platform": "cli",
                "is_runner": self.isRunner,
                "is_container": str(os.environ.get("PKSCREENER_DOCKER", "")).lower() in ("yes", "y", "on", "true", "1"),
                "one_file_bundle": self.onefile,
                
                # Performance
                "elapsed_time": round(time.time() - self.start_time, 2),
            }
            
            # Add label if provided
            if label:
                event_params["event_label"] = label
            
            # Add value if provided (numeric)
            if value is not None:
                event_params["event_value"] = value
            
            # Add location dimensions (for geo analysis)
            if current_location:
                if "country" in current_location:
                    event_params["country"] = current_location["country"]
                if "region" in current_location:
                    event_params["region"] = current_location["region"]
                if "city" in current_location:
                    event_params["city"] = current_location["city"]
            
            # Add custom dimensions (for detailed analysis)
            if custom_dimensions:
                for key, val in custom_dimensions.items():
                    event_params[f"dim_{key}"] = str(val)[:100]  # Limit length
            
            # Add repository info for GitHub Runner
            if self.isRunner:
                try:
                    owner = os.popen('git ls-remote --get-url origin | cut -d/ -f4').read().replace("\n", "")
                    repo = os.popen('git ls-remote --get-url origin | cut -d/ -f5').read().replace(".git", "").replace("\n", "")
                    event_params["repo_owner"] = owner
                    event_params["repo"] = repo
                except Exception:
                    pass
            
            # Send the event
            PKUserService().send_event(f"{category}_{action}", event_params)
            
            # Update feature usage counters
            if category == AnalyticsCategory.FEATURE:
                feature_name = label or action
                self._feature_usage[feature_name] = self._feature_usage.get(feature_name, 0) + 1
                
        except Exception:
            pass
    
    def _is_premium_user(self):
        """Check if current user has premium subscription."""
        try:
            from pkscreener.classes.PKUserRegistration import PKUserRegistration
            # This just checks if user is logged in (premium trial or paid)
            return PKUserRegistration().userID != 0
        except Exception:
            return False

    def track_scan(self, scan_type, result_count, duration_seconds, 
                   menu_path=None, success=True):
        """
        Track a scanner execution (convenience method).
        
        Args:
            scan_type (str): Type of scan (e.g., "volume_gainers", "breakouts")
            result_count (int): Number of results found
            duration_seconds (float): How long the scan took
            menu_path (str, optional): Menu navigation path
            success (bool): Whether scan completed successfully
        """
        self.send_event(
            category=AnalyticsCategory.SCAN,
            action=AnalyticsAction.COMPLETE,
            label=AnalyticsLabel.SUCCESS if success else AnalyticsLabel.FAILURE,
            value=result_count,
            custom_dimensions={
                "scan_type": scan_type,
                "duration": round(duration_seconds, 2),
                "menu_path": menu_path[:100] if menu_path else None
            }
        )

    def track_performance(self, operation, duration_seconds, success=True):
        """
        Track performance metrics.
        
        Args:
            operation (str): Operation name (e.g., "data_load", "calculation")
            duration_seconds (float): Operation duration
            success (bool): Whether operation succeeded
        """
        self.send_event(
            category=AnalyticsCategory.PERFORMANCE,
            action=operation,
            label=AnalyticsLabel.SUCCESS if success else AnalyticsLabel.FAILURE,
            value=int(duration_seconds * 1000),  # Convert to milliseconds
            custom_dimensions={
                "duration_ms": int(duration_seconds * 1000)
            }
        )

    def track_error(self, error_type, error_message, context=None):
        """
        Track errors for debugging and reliability monitoring.
        
        Args:
            error_type (str): Type of error (e.g., "NetworkError", "ValueError")
            error_message (str): Error message (truncated)
            context (dict, optional): Additional context
        """
        self.send_event(
            category=AnalyticsCategory.ERROR,
            action=error_type,
            label=AnalyticsLabel.FAILURE,
            custom_dimensions={
                "error_message": error_message[:200],
                "context": str(context)[:200] if context else None
            }
        )

    def track_feature_usage(self, feature_name, menu_path=None, **kwargs):
        """
        Track feature usage for adoption analysis.
        
        Args:
            feature_name (str): Name of the feature used
            menu_path (str, optional): Menu navigation path
            **kwargs: Additional custom dimensions
        """
        self.send_event(
            category=AnalyticsCategory.FEATURE,
            action=AnalyticsAction.USE,
            label=feature_name,
            custom_dimensions={
                "menu_path": menu_path[:100] if menu_path else None,
                **kwargs
            }
        )

    def collectMetrics(self, user=None, async_mode=True):
        """
        Collect user metrics in non-blocking mode.
        
        Args:
            user: Optional user identifier
            async_mode (bool): If True, run asynchronously
        """
        if not self.configManager.enableUsageAnalytics:
            return
        
        if async_mode:
            self._executor.submit(self._collect_metrics_sync, user)
        else:
            self._collect_metrics_sync(user)

    def _collect_metrics_sync(self, user=None):
        """Synchronous metrics collection (runs in background thread)."""
        try:
            self.getUserName()
            
            # Wait for location if needed
            if not self._location_fetched:
                for _ in range(10):
                    if self._location_fetched:
                        break
                    time.sleep(0.01)
            
            # Send user info event with custom dimensions
            self.send_event(
                category=AnalyticsCategory.USER,
                action=AnalyticsAction.LOGIN,
                label=AnalyticsLabel.INFO,
                custom_dimensions={
                    "user_exists": bool(user),
                    "premium": self._is_premium_user()
                }
            )
        except Exception:
            pass

    def getUserName(self):
        """Get anonymized user identifier."""
        return self.username

    def getApproxLocationInfo(self, use_cache=True, timeout=2):
        """Get approximate location information."""
        with self._location_lock:
            if use_cache and self.locationInfo:
                return self.locationInfo
        
        if not use_cache:
            try:
                url = 'http://ipinfo.io/json'
                f = fetcher()
                response = f.fetchURL(url=url, timeout=timeout, headers={'user-agent': f'{random_user_agent()}'})
                if response and response.status_code == 200:
                    data = json.loads(response.text)
                    with self._location_lock:
                        self.locationInfo = data
                        self._location_fetched = True
                    return data
            except Exception:
                pass
        
        return {"country": "Unknown", "region": "Unknown"}

    def flush(self, timeout=5):
        """Wait for all pending analytics events to complete."""
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analytics")

    def __del__(self):
        """Cleanup executor on object destruction."""
        if hasattr(self, '_executor') and self._executor:
            try:
                # Send session end event
                self.send_event(
                    AnalyticsCategory.APP,
                    AnalyticsAction.EXIT,
                    AnalyticsLabel.INFO,
                    value=int(time.time() - self._session_start_time)
                )
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass


# =============================================================================
# HELPER DECORATORS FOR EASY TRACKING
# =============================================================================

def track_feature(feature_name):
    """
    Decorator to automatically track feature usage.
    
    Usage:
        @track_feature("ATR_Trailing_Stop")
        def my_function():
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                analytics.track_feature_usage(
                    feature_name,
                    duration_ms=int((time.time() - start_time) * 1000),
                    success=True
                )
                return result
            except Exception as e:
                analytics.track_feature_usage(
                    feature_name,
                    duration_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error=str(e)[:100]
                )
                raise
        return wrapper
    return decorator


def track_performance(operation_name):
    """
    Decorator to automatically track performance.
    
    Usage:
        @track_performance("data_loading")
        def load_data():
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                analytics.track_performance(
                    operation_name,
                    time.time() - start_time,
                    success=True
                )
                return result
            except Exception as e:
                analytics.track_performance(
                    operation_name,
                    time.time() - start_time,
                    success=False
                )
                raise
        return wrapper
    return decorator
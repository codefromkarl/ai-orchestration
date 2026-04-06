"""
Fact-driven coordination system for Taskplane.

This module implements a general-purpose fact storage and observation system
that enables decentralized coordination between agents through shared facts,
rather than command-based dispatching.

Key concepts:
- Facts are immutable statements about system state
- Agents observe facts and react based on their interests
- Work is claimed through atomic fact-based operations
- Facts have TTL for automatic cleanup and failure recovery
- Fact chains enable causal tracing and auditability
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Set
from threading import Lock, RLock
import time

from ..models import WorkItem, WorkClaim, WorkStatus


class FactCategory(Enum):
    """Categories of facts in the system."""
    TASK = "task"
    WORK = "work"
    AGENT = "agent"
    SESSION = "session"
    POLICY = "policy"
    CONTROL = "control"
    HEARTBEAT = "heartbeat"


class FactType(Enum):
    """Types of facts that can be published."""
    # Task lifecycle
    TASK_CREATED = "task_created"
    TASK_READY = "task_ready"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_BLOCKED = "task_blocked"
    
    # Work claiming
    WORK_CLAIMED = "work_claimed"
    WORK_RELEASED = "work_released"
    WORK_EXPIRED = "work_expired"
    
    # Agent lifecycle
    AGENT_REGISTERED = "agent_registered"
    AGENT_HEARTBEAT = "agent_heartbeat"
    AGENT_UNREGISTERED = "agent_unregistered"
    
    # Session facts
    SESSION_STARTED = "session_started"
    SESSION_CHECKPOINT = "session_checkpoint"
    SESSION_RESUMED = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    
    # Policy and control
    POLICY_UPDATED = "policy_updated"
    CONTROL_EMERGENCY_STOP = "control_emergency_stop"
    CONTROL_WORK_REASSIGN = "control_work_reassign"
    CONFIG_UPDATED = "config_updated"
    
    # Verification and validation
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    VALIDATION_REQUIRED = "validation_required"


@dataclass(frozen=True)
class Fact:
    """
    Immutable fact representing a statement about system state.
    
    Facts are the fundamental coordination primitives in the fact-driven system.
    They are published to the fact store and observed by interested agents.
    """
    fact_id: str
    category: FactCategory
    fact_type: FactType
    entity_id: str  # The entity this fact is about (task_id, agent_id, etc.)
    timestamp: float
    payload: Dict[str, Any] = field(default_factory=dict)
    ttl_seconds: int = 300  # 5 minutes default TTL
    parent_fact_id: Optional[str] = None  # For causal chains
    correlation_id: Optional[str] = None  # For grouping related facts
    
    def is_expired(self, current_time: Optional[float] = None) -> bool:
        """Check if this fact has expired based on TTL."""
        if current_time is None:
            current_time = time.time()
        return current_time > (self.timestamp + self.ttl_seconds)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert fact to dictionary representation."""
        return {
            "fact_id": self.fact_id,
            "category": self.category.value,
            "fact_type": self.fact_type.value,
            "entity_id": self.entity_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "ttl_seconds": self.ttl_seconds,
            "parent_fact_id": self.parent_fact_id,
            "correlation_id": self.correlation_id,
            "expired": self.is_expired()
        }
    
    @classmethod
    def create_task_created(cls, task_id: str, payload: Dict[str, Any], 
                          ttl_seconds: int = 3600) -> 'Fact':
        """Create a TASK_CREATED fact."""
        return cls(
            fact_id=f"task-created-{task_id}-{int(time.time()*1000)}",
            category=FactCategory.TASK,
            fact_type=FactType.TASK_CREATED,
            entity_id=task_id,
            timestamp=time.time(),
            payload=payload,
            ttl_seconds=ttl_seconds
        )
    
    @classmethod
    def create_task_ready(cls, task_id: str, payload: Dict[str, Any],
                         parent_fact_id: Optional[str] = None,
                         ttl_seconds: int = 300) -> 'Fact':
        """Create a TASK_READY fact."""
        return cls(
            fact_id=f"task-ready-{task_id}-{int(time.time()*1000)}",
            category=FactCategory.TASK,
            fact_type=FactType.TASK_READY,
            entity_id=task_id,
            timestamp=time.time(),
            payload=payload,
            ttl_seconds=ttl_seconds,
            parent_fact_id=parent_fact_id
        )
    
    @classmethod
    def create_work_claimed(cls, task_id: str, worker_id: str,
                           claimed_paths: List[str],
                           parent_fact_id: Optional[str] = None,
                           ttl_seconds: int = 900) -> 'Fact':  # 15 minute lease
        """Create a WORK_CLAIMED fact."""
        return cls(
            fact_id=f"work-claimed-{task_id}-{worker_id}-{int(time.time()*1000)}",
            category=FactCategory.WORK,
            fact_type=FactType.WORK_CLAIMED,
            entity_id=task_id,
            timestamp=time.time(),
            payload={
                "worker_id": worker_id,
                "claimed_paths": claimed_paths,
                "claimed_at": time.time(),
                "lease_expires_at": time.time() + ttl_seconds
            },
            ttl_seconds=ttl_seconds,
            parent_fact_id=parent_fact_id
        )
    
    @classmethod
    def create_agent_registered(cls, agent_id: str, 
                               capabilities: List[str],
                               ttl_seconds: int = 300) -> 'Fact':
        """Create an AGENT_REGISTERED fact."""
        return cls(
            fact_id=f"agent-reg-{agent_id}-{int(time.time()*1000)}",
            category=FactCategory.AGENT,
            fact_type=FactType.AGENT_REGISTERED,
            entity_id=agent_id,
            timestamp=time.time(),
            payload={
                "agent_id": agent_id,
                "capabilities": capabilities,
                "registered_at": time.time()
            },
            ttl_seconds=ttl_seconds
        )
    
    @classmethod
    def create_agent_heartbeat(cls, agent_id: str,
                              status: str = "active",
                              ttl_seconds: int = 60) -> 'Fact':
        """Create an AGENT_HEARTBEAT fact."""
        return cls(
            fact_id=f"agent-hb-{agent_id}-{int(time.time()*1000)}",
            category=FactCategory.HEARTBEAT,
            fact_type=FactType.AGENT_HEARTBEAT,
            entity_id=agent_id,
            timestamp=time.time(),
            payload={
                "agent_id": agent_id,
                "status": status,
                "timestamp": time.time()
            },
            ttl_seconds=ttl_seconds
        )
    
    @classmethod
    def create_emergency_stop(cls, reason: str, initiated_by: str,
                             ttl_seconds: int = 60) -> 'Fact':
        """Create a CONTROL_EMERGENCY_STOP fact."""
        return cls(
            fact_id=f"emergency-stop-{int(time.time()*1000)}",
            category=FactCategory.CONTROL,
            fact_type=FactType.CONTROL_EMERGENCY_STOP,
            entity_id="system",
            timestamp=time.time(),
            payload={
                "reason": reason,
                "initiated_by": initiated_by,
                "timestamp": time.time()
            },
            ttl_seconds=ttl_seconds
        )


@dataclass
class FactSubscription:
    """Represents a subscription to specific fact types."""
    subscriber_id: str
    fact_types: Set[FactType]
    entity_filter: Optional[str] = None  # If set, only receive facts for this entity
    callback: Callable[[Fact], None] = field(repr=False)
    active: bool = True


class FactStore(Protocol):
    """Protocol defining the fact store interface."""
    
    def publish_fact(self, fact: Fact) -> str:
        """Publish a fact to the store."""
        ...
    
    def get_facts(self, entity_id: Optional[str] = None,
                  fact_type: Optional[FactType] = None,
                  category: Optional[FactCategory] = None,
                  include_expired: bool = False) -> List[Fact]:
        """Get facts matching the criteria."""
        ...
    
    def get_fact_chain(self, fact_id: str) -> List[Fact]:
        """Get the chain of facts leading to this fact (oldest first)."""
        ...
    
    def subscribe(self, subscriber_id: str, fact_types: Set[FactType],
                  entity_filter: Optional[str] = None,
                  callback: Callable[[Fact], None]) -> str:
        """Subscribe to facts."""
        ...
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from facts."""
        ...
    
    def cleanup_expired(self) -> int:
        """Remove expired facts and return count of removed facts."""
        ...
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the fact store."""
        ...


@dataclass
class InMemoryFactStore:
    """
    In-memory implementation of the fact store.
    
    Suitable for testing and development. For production, use PostgresFactStore.
    """
    _facts: Dict[str, Fact] = field(default_factory=dict)
    _subscriptions: Dict[str, FactSubscription] = field(default_factory=dict)
    _entity_index: Dict[str, Set[str]] = field(default_factory=dict)  # entity_id -> fact_ids
    _type_index: Dict[FactType, Set[str]] = field(default_factory=dict)  # fact_type -> fact_ids
    _category_index: Dict[FactCategory, Set[str]] = field(default_factory=dict)  # category -> fact_ids
    _lock: RLock = field(default_factory=RLock)
    
    def publish_fact(self, fact: Fact) -> str:
        """Publish a fact to the store."""
        with self._lock:
            # Store the fact
            self._facts[fact.fact_id] = fact
            
            # Update indices
            self._entity_index.setdefault(fact.entity_id, set()).add(fact.fact_id)
            self._type_index.setdefault(fact.fact_type, set()).add(fact.fact_id)
            self._category_index.setdefault(fact.category, set()).add(fact.fact_id)
            
            # Notify subscribers
            self._notify_subscribers(fact)
            
            return fact.fact_id
    
    def get_facts(self, entity_id: Optional[str] = None,
                  fact_type: Optional[FactType] = None,
                  category: Optional[FactCategory] = None,
                  include_expired: bool = False) -> List[Fact]:
        """Get facts matching the criteria."""
        with self._lock:
            # Start with all facts or filter by entity
            if entity_id is not None:
                fact_ids = self._entity_index.get(entity_id, set())
            else:
                fact_ids = set(self._facts.keys())
            
            # Filter by fact type
            if fact_type is not None:
                fact_ids &= self._type_index.get(fact_type, set())
            
            # Filter by category
            if category is not None:
                fact_ids &= self._category_index.get(category, set())
            
            # Get facts and filter by expiration if needed
            facts = []
            for fid in fact_ids:
                if fid in self._facts:
                    fact = self._facts[fid]
                    if include_expired or not fact.is_expired():
                        facts.append(fact)
            
            # Sort by timestamp
            facts.sort(key=lambda f: f.timestamp)
            return facts
    
    def get_fact_chain(self, fact_id: str) -> List[Fact]:
        """Get the chain of facts leading to this fact (oldest first)."""
        with self._lock:
            chain = []
            current_fact_id = fact_id
            
            # Follow parent pointers backwards
            while current_fact_id and current_fact_id in self._facts:
                fact = self._facts[current_fact_id]
                chain.append(fact)
                current_fact_id = fact.parent_fact_id
            
            # Reverse to get oldest first
            return list(reversed(chain))
    
    def subscribe(self, subscriber_id: str, fact_types: Set[FactType],
                  entity_filter: Optional[str] = None,
                  callback: Callable[[Fact], None]) -> str:
        """Subscribe to facts."""
        with self._lock:
            subscription_id = f"sub-{subscriber_id}-{len(self._subscriptions)}"
            subscription = FactSubscription(
                subscriber_id=subscriber_id,
                fact_types=fact_types,
                entity_filter=entity_filter,
                callback=callback
            )
            self._subscriptions[subscription_id] = subscription
            return subscription_id
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from facts."""
        with self._lock:
            if subscription_id in self._subscriptions:
                del self._subscriptions[subscription_id]
                return True
            return False
    
    def _notify_subscribers(self, fact: Fact) -> None:
        """Notify all relevant subscribers of a new fact."""
        # Create a list to avoid modification during iteration
        subscriptions = list(self._subscriptions.values())
        
        for subscription in subscriptions:
            if not subscription.active:
                continue
                
            # Check if fact type matches subscription
            if fact.fact_type not in subscription.fact_types:
                continue
            
            # Check entity filter if present
            if (subscription.entity_filter is not None and 
                fact.entity_id != subscription.entity_filter):
                continue
            
            # Call the callback (in a real system, this might be async)
            try:
                subscription.callback(fact)
            except Exception as e:
                # In production, log this error appropriately
                print(f"Error in fact subscription callback: {e}")
    
    def cleanup_expired(self) -> int:
        """Remove expired facts and return count of removed facts."""
        with self._lock:
            now = time.time()
            expired_ids = []
            
            for fact_id, fact in self._facts.items():
                if fact.is_expired(now):
                    expired_ids.append(fact_id)
            
            # Remove expired facts
            for fact_id in expired_ids:
                fact = self._facts.pop(fact_id, None)
                if fact:
                    # Remove from indices
                    self._entity_index.get(fact.entity_id, set()).discard(fact_id)
                    self._type_index.get(fact.fact_type, set()).discard(fact_id)
                    self._category_index.get(fact.category, set()).discard(fact_id)
            
            return len(expired_ids)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the fact store."""
        with self._lock:
            now = time.time()
            total_facts = len(self._facts)
            expired_facts = sum(1 for f in self._facts.values() if f.is_expired(now))
            active_facts = total_facts - expired_facts
            
            # Count by category and type
            category_counts: Dict[str, int] = {}
            type_counts: Dict[str, int] = {}
            
            for fact in self._facts.values():
                if not fact.is_expired(now):
                    cat = fact.category.value
                    typ = fact.fact_type.value
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                    type_counts[typ] = type_counts.get(typ, 0) + 1
            
            return {
                "total_facts": total_facts,
                "active_facts": active_facts,
                "expired_facts": expired_facts,
                "subscription_count": len([s for s in self._subscriptions.values() if s.active]),
                "category_counts": category_counts,
                "type_counts": type_counts
            }


# Global fact store instance (in a real system, this would be dependency injected)
_fact_store: Optional[InMemoryFactStore] = None


def get_fact_store() -> InMemoryFactStore:
    """Get the global fact store instance."""
    global _fact_store
    if _fact_store is None:
        _fact_store = InMemoryFactStore()
    return _fact_store


def publish_fact(fact: Fact) -> str:
    """Convenience function to publish a fact to the global store."""
    return get_fact_store().publish_fact(fact)


def get_facts(entity_id: Optional[str] = None,
              fact_type: Optional[FactType] = None,
              category: Optional[FactCategory] = None,
              include_expired: bool = False) -> List[Fact]:
    """Convenience function to get facts from the global store."""
    return get_fact_store().get_facts(entity_id, fact_type, category, include_expired)


def get_fact_chain(fact_id: str) -> List[Fact]:
    """Convenience function to get fact chain from the global store."""
    return get_fact_store().get_fact_chain(fact_id)


def subscribe(subscriber_id: str, fact_types: Set[FactType],
              entity_filter: Optional[str] = None,
              callback: Callable[[Fact], None]) -> str:
    """Convenience function to subscribe to facts."""
    return get_fact_store().subscribe(subscriber_id, fact_types, entity_filter, callback)


def unsubscribe(subscription_id: str) -> bool:
    """Convenience function to unsubscribe from facts."""
    return get_fact_store().unsubscribe(subscription_id)


def cleanup_expired() -> int:
    """Convenience function to cleanup expired facts."""
    return get_fact_store().cleanup_expired()


def get_fact_store_stats() -> Dict[str, Any]:
    """Convenience function to get fact store statistics."""
    return get_fact_store().get_stats()
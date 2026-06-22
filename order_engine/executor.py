"""Professional order execution with retry and status tracking."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from core.events import Event, EventBus, EventType
from core.logging_config import get_logger
from core.metrics import metrics
from database.models import Order, OrderStatus
from database.repository import DatabaseRepository
from order_engine.models import OrderRequest, OrderResult
from order_engine.validator import OrderValidator
from risk_management.manager import RiskManager
from strategies.base import Signal

logger = get_logger("order_executor")


class OrderExecutor:
    """
    Order execution pipeline:
    Signal → Risk Check → Validation → Submission → Confirmation → Logging
    """

    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 1.0

    def __init__(
        self,
        event_bus: EventBus,
        risk_manager: RiskManager,
        broker_client,
        db_repo: DatabaseRepository | None = None,
    ):
        self.event_bus = event_bus
        self.risk_manager = risk_manager
        self.broker = broker_client
        self.db_repo = db_repo
        self.validator = OrderValidator()
        self._pending_orders: dict[str, OrderRequest] = {}
        self._execution_lock = asyncio.Lock()

    async def execute_signal(self, signal: Signal) -> OrderResult:
        """Full execution pipeline from signal to confirmed order."""
        pipeline_start = time.perf_counter()

        async with self._execution_lock:
            try:
                # Step 1: Risk check
                await self.risk_manager.approve_signal(signal)

                # Step 2: Validate and create order request
                request = self.validator.validate_signal(signal)

                # Step 3: Persist order
                db_order = None
                if self.db_repo:
                    db_order = await self.db_repo.create_order(
                        Order(
                            id=request.id,
                            symbol=request.symbol,
                            side=request.side,
                            order_type=request.order_type,
                            quantity=request.quantity,
                            price=request.price,
                            status=OrderStatus.PENDING,
                            strategy_name=request.strategy_name,
                            signal_id=request.signal_id,
                            metadata_json=request.metadata,
                        )
                    )

                # Step 4: Submit with retry
                result = await self._submit_with_retry(request)

                # Step 5: Update database
                if self.db_repo and db_order:
                    status = OrderStatus.EXECUTED if result.success else OrderStatus.FAILED
                    await self.db_repo.update_order(
                        request.id,
                        status=status,
                        broker_order_id=result.broker_order_id,
                        error_message=result.error,
                        latency_ms=result.latency_ms,
                        executed_at=result.executed_at,
                    )

                # Step 6: Update risk state
                if result.success:
                    self.risk_manager.record_success()
                else:
                    self.risk_manager.record_failure()

                total_latency = (time.perf_counter() - pipeline_start) * 1000
                metrics.record_latency("end_to_end_latency", total_latency, signal.symbol)

                # Step 7: Publish event
                event_type = EventType.ORDER_EXECUTED if result.success else EventType.ORDER_FAILED
                await self.event_bus.publish(
                    Event(
                        type=event_type,
                        source="order_executor",
                        data={
                            **result.to_dict(),
                            "symbol": signal.symbol,
                            "end_to_end_latency_ms": total_latency,
                        },
                    )
                )

                logger.info(
                    "order_pipeline_complete",
                    order_id=result.order_id,
                    symbol=signal.symbol,
                    success=result.success,
                    total_latency_ms=total_latency,
                )
                return result

            except Exception as exc:
                self.risk_manager.record_failure()
                logger.error("order_pipeline_error", symbol=signal.symbol, error=str(exc))
                raise

    async def _submit_with_retry(self, request: OrderRequest) -> OrderResult:
        """Submit order with exponential backoff retry."""
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = await self._submit_order(request)
                if result.success:
                    return result
                last_error = result.error
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "order_submit_retry",
                    attempt=attempt,
                    symbol=request.symbol,
                    error=last_error,
                )

            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)

        return OrderResult(
            order_id=request.id,
            success=False,
            status="failed",
            error=f"Failed after {self.MAX_RETRIES} attempts: {last_error}",
        )

    async def _submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit order to broker and track latency."""
        start = time.perf_counter()
        self._pending_orders[request.id] = request

        await self.event_bus.publish(
            Event(
                type=EventType.ORDER_SUBMITTED,
                source="order_executor",
                data=request.to_dict(),
            )
        )

        try:
            broker_result = await self.broker.place_order(
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
            )
            submission_latency = (time.perf_counter() - start) * 1000
            metrics.record_latency("order_submission_latency", submission_latency, request.symbol)

            result = OrderResult(
                order_id=request.id,
                success=broker_result.get("success", False),
                status=broker_result.get("status", "submitted"),
                broker_order_id=broker_result.get("order_id"),
                message=broker_result.get("message", ""),
                latency_ms=submission_latency,
                executed_at=datetime.now(timezone.utc) if broker_result.get("success") else None,
            )

            if result.success:
                metrics.record_latency("execution_latency", submission_latency, request.symbol)
                metrics.increment("orders_executed")

            return result

        except Exception as exc:
            submission_latency = (time.perf_counter() - start) * 1000
            return OrderResult(
                order_id=request.id,
                success=False,
                status="failed",
                error=str(exc),
                latency_ms=submission_latency,
            )
        finally:
            self._pending_orders.pop(request.id, None)

    def get_pending_orders(self) -> list[OrderRequest]:
        return list(self._pending_orders.values())

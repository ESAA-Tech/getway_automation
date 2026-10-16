"""
Concurrent Async Worker Pool with Rate Limiting.
Coordinates parallel execution across up to 100+ gateways without switch or socket saturation.
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("pro.engine.worker_pool")


@dataclass
class TaskResult:
    """Outcome of an isolated gateway task."""
    gateway_id: str
    gateway_ip: str
    status: str = "PENDING"  # SUCCESS, FAILED, TIMEOUT, SKIPPED
    elapsed_seconds: float = 0.0
    result: Optional[Any] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class WorkerPool:
    """
    Controlled concurrency pool for high-throughput gateway orchestration.
    Maintains rate-limiting to prevent municipal VPN or cellular APN congestion.
    """

    def __init__(self, max_workers: int = 15, timeout_per_task: int = 30):
        self.max_workers = max_workers
        self.timeout_per_task = timeout_per_task

    def execute_all(
        self,
        targets: List[Dict[str, Any]],
        task_fn: Callable[[Dict[str, Any]], Any],
        task_name: str = "Sync"
    ) -> List[TaskResult]:
        """
        Executes task_fn concurrently across all target gateways.
        Returns ordered task results.
        """
        total = len(targets)
        logger.info(f"Starting {task_name} across {total} gateways with {self.max_workers} concurrent workers...")

        results: List[TaskResult] = []
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_gw = {}
            for gw in targets:
                gw_id = gw.get("gateway_id", "GW")
                gw_ip = gw.get("ip_address", "0.0.0.0")
                future = executor.submit(self._worker_wrapper, task_fn, gw)
                future_to_gw[future] = (gw_id, gw_ip)

            completed_count = 0
            for future in as_completed(future_to_gw):
                gw_id, gw_ip = future_to_gw[future]
                completed_count += 1
                try:
                    res = future.result(timeout=self.timeout_per_task)
                    results.append(res)
                    status_symbol = "[+]" if res.status == "SUCCESS" else "[-]"
                    logger.info(f"{status_symbol} [{completed_count}/{total}] {gw_id} ({gw_ip}) completed in {res.elapsed_seconds:.2f}s: {res.status}")
                except Exception as e:
                    logger.error(f"[-] [{completed_count}/{total}] {gw_id} ({gw_ip}) error: {e}")
                    results.append(TaskResult(
                        gateway_id=gw_id,
                        gateway_ip=gw_ip,
                        status="FAILED",
                        error=str(e)
                    ))

        total_elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r.status == "SUCCESS")
        fail_count = total - success_count
        logger.info(f"Finished {task_name}: {success_count}/{total} successful in {total_elapsed:.2f}s ({fail_count} failed).")

        return results

    def _worker_wrapper(
        self,
        task_fn: Callable[[Dict[str, Any]], Any],
        gw: Dict[str, Any]
    ) -> TaskResult:
        gw_id = gw.get("gateway_id", "GW")
        gw_ip = gw.get("ip_address", "0.0.0.0")
        t0 = time.time()

        try:
            val = task_fn(gw)
            elapsed = time.time() - t0
            return TaskResult(
                gateway_id=gw_id,
                gateway_ip=gw_ip,
                status="SUCCESS",
                elapsed_seconds=elapsed,
                result=val
            )
        except Exception as e:
            elapsed = time.time() - t0
            return TaskResult(
                gateway_id=gw_id,
                gateway_ip=gw_ip,
                status="FAILED",
                elapsed_seconds=elapsed,
                error=str(e)
            )

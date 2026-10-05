def chunk_items(items, batch_size):
    """
    Split a sequence into fixed-size batches.

    Parameters
    ----------
    items : sequence
        Items to split.
    batch_size : int
        Maximum number of items per batch.

    Yields
    ------
    list
        Consecutive batches.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    items = list(items)

    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def adaptive_download(
    items,
    downloader,
    initial_batch_size=250,
    minimum_batch_size=10,
    on_progress=None,
):
    """
    Download items in batches and recursively split failed batches.

    This is useful for REST services where large object-ID requests may fail
    because of service limits, timeouts, payload size, or gateway errors.

    Parameters
    ----------
    items : sequence
        IDs or other values to process.
    downloader : callable
        Function receiving one list of items. It should raise an exception
        when the batch fails.
    initial_batch_size : int, optional
        Starting batch size.
    minimum_batch_size : int, optional
        Smallest batch size allowed before failure is propagated.
    on_progress : callable, optional
        Callback invoked as:

            on_progress(event, payload)

        Supported events:
            "batch_start"
            "batch_success"
            "batch_split"
            "batch_failed"

    Returns
    -------
    list
        Results returned by successful downloader calls.
    """
    if initial_batch_size <= 0:
        raise ValueError(
            "initial_batch_size must be greater than zero."
        )

    if minimum_batch_size <= 0:
        raise ValueError(
            "minimum_batch_size must be greater than zero."
        )

    if minimum_batch_size > initial_batch_size:
        raise ValueError(
            "minimum_batch_size cannot exceed initial_batch_size."
        )

    items = list(items)

    if not items:
        return []

    results = []

    def notify(event, **payload):
        if on_progress:
            on_progress(event, payload)

    def process_batch(batch):
        notify(
            "batch_start",
            size=len(batch),
        )

        try:
            result = downloader(batch)

            results.append(result)

            notify(
                "batch_success",
                size=len(batch),
            )

            return

        except Exception as exc:
            if len(batch) <= minimum_batch_size:
                notify(
                    "batch_failed",
                    size=len(batch),
                    error=str(exc),
                )
                raise

            midpoint = len(batch) // 2

            left = batch[:midpoint]
            right = batch[midpoint:]

            if not left or not right:
                notify(
                    "batch_failed",
                    size=len(batch),
                    error=str(exc),
                )
                raise

            notify(
                "batch_split",
                original_size=len(batch),
                left_size=len(left),
                right_size=len(right),
                error=str(exc),
            )

            process_batch(left)
            process_batch(right)

    for batch in chunk_items(items, initial_batch_size):
        process_batch(batch)

    return results
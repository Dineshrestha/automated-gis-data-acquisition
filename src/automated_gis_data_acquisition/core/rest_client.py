import json
import time
import urllib.error
import urllib.parse
import urllib.request


TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


def post_json(
    url,
    params,
    timeout=120,
    retries=3,
    user_agent="Automated-GIS-Data-Acquisition/0.1",
):
    """
    POST form-encoded parameters to a REST endpoint and return decoded JSON.

    Retries transient HTTP/ArcGIS REST failures using exponential backoff.

    Parameters
    ----------
    url : str
        REST endpoint URL.
    params : dict
        Parameters to POST.
    timeout : int, optional
        Request timeout in seconds.
    retries : int, optional
        Maximum number of attempts.
    user_agent : str, optional
        HTTP User-Agent header.

    Returns
    -------
    dict | list
        Decoded JSON response.
    """
    data = urllib.parse.urlencode(params).encode("utf-8")

    headers = {
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8")

            result = json.loads(text)

            # ArcGIS Server can return HTTP 200 while embedding an
            # application-level error object in the JSON response.
            if isinstance(result, dict) and "error" in result:
                code = result["error"].get("code")

                if code in TRANSIENT_HTTP_CODES and attempt < retries:
                    time.sleep(2 ** attempt)
                    continue

            return result

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc

            if attempt >= retries:
                raise

            time.sleep(2 ** attempt)

    raise last_error


def format_arcgis_error(error):
    """
    Convert an ArcGIS REST error dictionary into a readable message.
    """
    code = error.get("code", "Unknown")
    message = error.get("message", "ArcGIS REST error")
    details = error.get("details") or []

    detail_text = " | " + " | ".join(details) if details else ""

    return "ArcGIS REST error {}: {}{}".format(
        code,
        message,
        detail_text,
    )
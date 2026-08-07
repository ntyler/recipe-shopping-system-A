(() => {
    "use strict";

    const planElement = document.getElementById("structuredEquipmentCanaryPlan");
    const startButton = document.getElementById("canaryStart");
    const stopButton = document.getElementById("canaryStop");
    const statusElement = document.getElementById("canaryStatus");
    const progressElement = document.getElementById("canaryProgress");
    const summaryElement = document.getElementById("canarySummary");
    const RUN_EVENT_URL = "/api/structured-equipment/authenticated-canary/run-event";
    const THROTTLE_MS = 25;

    if (!planElement || !startButton || !stopButton || !statusElement || !progressElement) {
        return;
    }

    let plan;
    try {
        plan = JSON.parse(planElement.textContent || "{}");
    } catch (_error) {
        statusElement.textContent = "The signed canary plan could not be loaded.";
        startButton.disabled = true;
        return;
    }

    const recipes = Array.isArray(plan.recipes) ? plan.recipes : [];
    const passCount = Number(plan.pass_count || 0);
    const expectedSamples = Number(plan.expected_sample_count || 0);
    const selectionModeIsValid = ["legacy_baseline", "structured_read"].includes(
        plan.selection_mode
    );
    const planIsBounded = recipes.length === 88
        && passCount === 6
        && expectedSamples === 528
        && selectionModeIsValid
        && recipes.every((recipe, index) => (
            recipe
            && Number(recipe.ordinal) === index + 1
            && typeof recipe.url === "string"
            && recipe.url.length > 0
            && typeof recipe.sample_token === "string"
            && recipe.sample_token.length > 0
        ));
    if (!planIsBounded || typeof plan.token !== "string" || !plan.token) {
        statusElement.textContent = "The server-controlled canary scope is invalid.";
        startButton.disabled = true;
        return;
    }

    let running = false;
    let cancelRequested = false;
    let activeController = null;
    let clientLatencies = [];

    const delay = (milliseconds) => new Promise((resolve) => {
        window.setTimeout(resolve, milliseconds);
    });

    const lifecycleEvent = async (event, reason, latencies = []) => {
        const response = await fetch(RUN_EVENT_URL, {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            redirect: "error",
            headers: {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Recipe-Equipment-Canary": plan.token,
            },
            body: JSON.stringify({
                event,
                reason,
                client_latencies_ms: latencies,
            }),
        });
        if (!response.ok) {
            throw new Error("server_rejected");
        }
        const payload = await response.json();
        if (!payload || payload.ok !== true) {
            throw new Error("invalid_json");
        }
        return payload.summary || {};
    };

    const setFinishedState = () => {
        running = false;
        activeController = null;
        startButton.disabled = true;
        stopButton.disabled = true;
    };

    const stopReasonForError = (error) => {
        if (error && error.name === "AbortError") {
            return "owner_cancelled";
        }
        if (error && ["http_error", "invalid_json", "server_rejected"].includes(error.message)) {
            return error.message;
        }
        if (error instanceof TypeError) {
            return "network_error";
        }
        return "unexpected_error";
    };

    const reportStop = async (reason) => {
        const event = reason === "owner_cancelled" ? "run_cancelled" : "client_error";
        try {
            await lifecycleEvent(event, reason, clientLatencies);
        } catch (_error) {
            // The visible stopped state is still authoritative when audit reporting fails.
        }
    };

    const runCanary = async () => {
        if (running) {
            return;
        }
        running = true;
        cancelRequested = false;
        clientLatencies = [];
        startButton.disabled = true;
        stopButton.disabled = false;
        summaryElement.hidden = true;
        progressElement.value = 0;
        statusElement.textContent = "Starting authenticated canary…";

        try {
            await lifecycleEvent("run_started", "owner_started");
            let sequence = 0;
            for (let passNumber = 1; passNumber <= passCount; passNumber += 1) {
                for (const recipe of recipes) {
                    if (cancelRequested) {
                        throw new DOMException("Owner cancelled", "AbortError");
                    }
                    sequence += 1;
                    activeController = new AbortController();
                    const requestStarted = performance.now();
                    const response = await fetch(`/api/recipe?url=${encodeURIComponent(recipe.url)}`, {
                        method: "GET",
                        credentials: "same-origin",
                        cache: "no-store",
                        redirect: "error",
                        signal: activeController.signal,
                        headers: {
                            "Accept": "application/json",
                            "X-Recipe-Equipment-Canary": recipe.sample_token,
                            "X-Recipe-Equipment-Canary-Pass": String(passNumber),
                            "X-Recipe-Equipment-Canary-Sequence": String(sequence),
                        },
                    });
                    clientLatencies.push(Number((performance.now() - requestStarted).toFixed(3)));
                    if (!response.ok) {
                        throw new Error("http_error");
                    }
                    const payload = await response.json();
                    if (!payload || typeof payload !== "object") {
                        throw new Error("invalid_json");
                    }
                    progressElement.value = sequence;
                    progressElement.textContent = `${sequence} of ${expectedSamples}`;
                    statusElement.textContent = `Pass ${passNumber} of ${passCount}: ${sequence} of ${expectedSamples} reads completed.`;
                    if (sequence < expectedSamples) {
                        await delay(THROTTLE_MS);
                    }
                }
            }
            const summary = await lifecycleEvent("run_completed", "completed", clientLatencies);
            summaryElement.textContent = JSON.stringify(summary, null, 2);
            summaryElement.hidden = false;
            statusElement.textContent = summary.complete
                ? "Authenticated canary completed successfully."
                : "The canary completed its requests but failed reconciliation.";
            setFinishedState();
        } catch (error) {
            const reason = stopReasonForError(error);
            await reportStop(reason);
            statusElement.textContent = `Canary stopped safely: ${reason.replaceAll("_", " ")}.`;
            setFinishedState();
        }
    };

    startButton.addEventListener("click", runCanary);
    stopButton.addEventListener("click", () => {
        if (!running) {
            return;
        }
        cancelRequested = true;
        stopButton.disabled = true;
        statusElement.textContent = "Stopping after the active request…";
        if (activeController) {
            activeController.abort();
        }
    });
})();

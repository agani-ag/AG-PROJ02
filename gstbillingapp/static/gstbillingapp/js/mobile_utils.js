// ===================================================
// Password Reset – One Time + 45 Seconds Expiry
// ===================================================

var RESET_EXPIRY_SECONDS = 45;
let resetExpiryTime = null;
let countdownInterval = null;

document.addEventListener("DOMContentLoaded", function () {
    const url = new URL(window.location.href);
    const passReset = url.searchParams.get("pass-reset");
    const cid = url.searchParams.get("cid");
    const resetTimer = url.searchParams.get("reset-timer");
    if (resetTimer) {
        RESET_EXPIRY_SECONDS = parseInt(resetTimer, 10);
    }

    if (passReset === "true" && cid && !localStorage.getItem("passResetDone")) {

        resetExpiryTime = Date.now() + RESET_EXPIRY_SECONDS * 1000;

        showPasswordResetSwal(cid);

        // Remove param from URL after first use
        url.searchParams.delete("pass-reset");
        window.history.replaceState({}, document.title, url.toString());
    }
});

// ===================================================
// SweetAlert2 UI – Simple password input, no validation
// ===================================================

function showPasswordResetSwal(cid) {
    Swal.fire({
        title: "🔐 Reset Password",
        input: "password",
        inputPlaceholder: "Enter new password",
        inputAttributes: {
            autocapitalize: "off",
            autocorrect: "off"
        },
        confirmButtonText: "Reset Password",
        confirmButtonColor: "#3085d6",
        allowOutsideClick: false,
        allowEscapeKey: false,
        showLoaderOnConfirm: true,
        customClass: {
            popup: "swal-mobile"
        },
        didOpen: () => {
            startCountdownTimer();
        },
        preConfirm: (password) => {
            return resetPasswordApi(cid, password);
        },
        willClose: () => {
            clearInterval(countdownInterval);
        }
    });
}

// ===================================================
// Countdown Timer + Progress Bar
// ===================================================

function startCountdownTimer() {
    const swalPopup = document.querySelector(".swal2-popup");
    if (!swalPopup) return;

    let timerBar = document.createElement("div");
    timerBar.id = "timer-bar";
    timerBar.style.height = "6px";
    timerBar.style.width = "100%";
    timerBar.style.background = "#22c55e";
    timerBar.style.borderRadius = "6px";
    timerBar.style.marginTop = "15px";
    timerBar.style.transition = "width 1s linear";
    swalPopup.appendChild(timerBar);

    let timerText = document.createElement("p");
    timerText.id = "reset-timer";
    timerText.style.marginTop = "8px";
    timerText.style.fontWeight = "600";
    timerText.style.color = "#dc2626";
    timerText.style.textAlign = "center";
    timerText.textContent = formatTime(RESET_EXPIRY_SECONDS);
    swalPopup.appendChild(timerText);

    const totalTime = RESET_EXPIRY_SECONDS * 1000;

    countdownInterval = setInterval(() => {
        const remaining = resetExpiryTime - Date.now();

        if (remaining <= 0) {
            clearInterval(countdownInterval);
            Swal.fire({
                icon: "error",
                title: "Time Expired",
                text: "Password reset time has expired. Please request again."
            });
            return;
        }

        const seconds = Math.floor(remaining / 1000);
        timerText.textContent = formatTime(seconds);

        const percent = (remaining / totalTime) * 100;
        timerBar.style.width = percent + "%";

        if (percent < 30) {
            timerBar.style.background = "#dc2626";
        }
    }, 1000);
}

function formatTime(seconds) {
    const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
    const ss = String(seconds % 60).padStart(2, "0");
    return `${mm}:${ss}`;
}

// ===================================================
// API Call
// ===================================================

function resetPasswordApi(cid, newPassword) {
    return fetch(`{% url 'v1customersresetpasswordapi' %}?cid=${cid}`, {
        method: "POST",
        headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: new URLSearchParams({
            new_password: newPassword
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === "success") {
            localStorage.setItem("passResetDone", "true");
            Swal.fire({
                icon: "success",
                title: "Password Reset",
                text: data.message
            }).then(() => {
                window.location.reload();
            });
        } else {
            Swal.showValidationMessage(data.message);
        }
    })
    .catch(() => {
        Swal.showValidationMessage("Network error. Try again.");
    });
}

// ===================================================
// CSRF Helper
// ===================================================

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        document.cookie.split(";").forEach(cookie => {
            cookie = cookie.trim();
            if (cookie.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
            }
        });
    }
    return cookieValue;
}

// ===================================================
// Password Reset – One Time + 1 Minute Expiry
// ===================================================

const RESET_EXPIRY_MINUTES = 1;
let resetExpiryTime = null;
let countdownInterval = null;

document.addEventListener("DOMContentLoaded", function () {

    const url = new URL(window.location.href);
    const passReset = url.searchParams.get("pass-reset");
    const cid = url.searchParams.get("cid");

    if (passReset === "true" && cid && !localStorage.getItem("passResetDone")) {

        resetExpiryTime = Date.now() + RESET_EXPIRY_MINUTES * 60 * 1000;

        showPasswordResetSwal(cid);

        // Remove param from URL
        url.searchParams.delete("pass-reset");
        window.history.replaceState({}, document.title, url.toString());
    }
});


// ===================================================
// SweetAlert UI
// ===================================================

function showPasswordResetSwal(cid) {
    Swal.fire({
        title: "🔐 Reset Password",
        html: `
            <div class="password-wrapper-reset-password">
                <input type="password"
                       id="swal-password"
                       class="swal2-input input-reset-password"
                       placeholder="Enter new password">

                <span class="toggle-password-reset-password"
                      id="toggle-password">👁️</span>
            </div>

            <div class="timer-wrapper-reset-password">
                <div class="timer-bar-reset-password" id="timer-bar"></div>
            </div>

            <p class="timer-text-reset-password">
                ⏳ Time left: <span id="reset-timer">01:00</span>
            </p>
        `,
        confirmButtonText: "Reset Password",
        confirmButtonColor: "#2563eb",
        allowOutsideClick: false,
        allowEscapeKey: false,
        customClass: {
            popup: "swal-popup-reset-password"
        },
        didOpen: () => {
            startCountdownTimer();
            initPasswordToggle();
        },
        preConfirm: () => {
            const password = document.getElementById("swal-password").value;

            const error = validatePassword(password);
            if (error) {
                Swal.showValidationMessage(error);
                return false;
            }

            if (Date.now() > resetExpiryTime) {
                Swal.showValidationMessage("Reset time expired");
                return false;
            }

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
    const timerText = document.getElementById("reset-timer");
    const timerBar = document.getElementById("timer-bar");

    const totalTime = RESET_EXPIRY_MINUTES * 60 * 1000;

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
        const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
        const ss = String(seconds % 60).padStart(2, "0");

        timerText.textContent = `${mm}:${ss}`;

        const percent = (remaining / totalTime) * 100;
        timerBar.style.width = percent + "%";

        if (percent < 30) {
            timerBar.style.background = "#dc2626";
        }
    }, 1000);
}


// ===================================================
// Show / Hide Password
// ===================================================

function initPasswordToggle() {
    const input = document.getElementById("swal-password");
    const toggle = document.getElementById("toggle-password");

    toggle.addEventListener("click", function () {
        const isHidden = input.type === "password";
        input.type = isHidden ? "text" : "password";
        toggle.textContent = isHidden ? "🙈" : "👁️";
    });
}


// ===================================================
// Password Validation
// ===================================================

function validatePassword(password) {
    if (!password) return "Password cannot be empty";
    if (password.length < 8) return "Minimum 8 characters required";
    if (!/[A-Z]/.test(password)) return "Add at least one uppercase letter";
    if (!/[a-z]/.test(password)) return "Add at least one lowercase letter";
    if (!/[0-9]/.test(password)) return "Add at least one number";
    return null;
}


// ===================================================
// API Call
// ===================================================

function resetPasswordApi(cid, newPassword) {

    return fetch(`/customers-reset-password-api/?cid=${cid}`, {
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
                window.location.href = "/login/";
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

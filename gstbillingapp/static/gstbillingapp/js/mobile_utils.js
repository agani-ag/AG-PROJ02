// ===================================================
// One-time Password Reset via URL (Advanced)
// ===================================================

document.addEventListener("DOMContentLoaded", function () {

    const url = new URL(window.location.href);
    const passReset = url.searchParams.get("pass-reset");
    const cid = url.searchParams.get("cid");

    const RESET_EXPIRY_MINUTES = 10; // link valid for 10 minutes
    const now = Date.now();

    const resetData = JSON.parse(localStorage.getItem("passResetData"));

    // Check if already used OR expired
    if (resetData) {
        const expiryTime = resetData.time + RESET_EXPIRY_MINUTES * 60 * 1000;
        if (now > expiryTime) {
            localStorage.removeItem("passResetData");
        }
    }

    if (
        passReset === "true" &&
        cid &&
        !localStorage.getItem("passResetDone")
    ) {

        localStorage.setItem(
            "passResetData",
            JSON.stringify({ time: now })
        );

        showPasswordResetSwal(cid);

        // Clean URL
        url.searchParams.delete("pass-reset");
        window.history.replaceState({}, document.title, url.toString());
    }
});


// ===================================================
// SweetAlert Password Reset Modal
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
        preConfirm: (password) => {
            const validationError = validatePassword(password);
            if (validationError) {
                Swal.showValidationMessage(validationError);
                return false;
            }
            return resetPasswordApi(cid, password);
        }
    });
}


// ===================================================
// Password Strength Validation
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
// API Call (Retry enabled)
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
    .then(response => response.json())
    .then(data => {
        if (data.status === "success") {

            localStorage.setItem("passResetDone", "true");
            localStorage.removeItem("passResetData");

            Swal.fire({
                icon: "success",
                title: "Password Reset",
                text: data.message,
                confirmButtonText: "Continue"
            }).then(() => {
                window.location.href = "/login/"; // 🔄 Redirect
            });

        } else {
            Swal.showValidationMessage(data.message);
        }
    })
    .catch(() => {
        Swal.showValidationMessage(
            "Network error. Please try again."
        );
    });
}


// ===================================================
// CSRF Helper
// ===================================================

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

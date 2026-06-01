const loginForm = document.getElementById("loginForm");
const message   = document.getElementById("message");

loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const email    = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const btn      = loginForm.querySelector("button");

    btn.textContent = "Signing in...";
    btn.disabled    = true;
    message.textContent = "";
    message.className   = "";

    try {
        const response = await fetch("http://127.0.0.1:8000/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });

        const data = await response.json();

        if (data.access_token) {
            localStorage.setItem("token", data.access_token);
            localStorage.setItem("role",  data.role);

            message.textContent = "Login successful ✓";
            message.className   = "success";

            // Role-based redirect
            setTimeout(() => {
                if      (data.role === "employee")    window.location.href = "agent.html";
                else if (data.role === "hr")          window.location.href = "hr_dashboard.html";
                else if (data.role === "admin")       window.location.href = "admin_dashboard.html";
                else if (data.role === "super_admin") window.location.href = "agent.html";
                else                                  window.location.href = "agent.html";
            }, 800);
        } else {
            message.textContent = data.message || "Login failed";
            btn.textContent     = "Login";
            btn.disabled        = false;
        }

    } catch (err) {
        message.textContent = "Cannot reach server — is the backend running?";
        btn.textContent     = "Login";
        btn.disabled        = false;
    }
});
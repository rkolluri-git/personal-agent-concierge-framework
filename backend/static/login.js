'use strict';
document.getElementById('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = document.getElementById('access-key');
  const status = document.getElementById('login-status');
  const token = input.value.trim();
  input.value = '';
  try {
    const response = await fetch('/auth/session', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
    if (!response.ok) throw new Error('Sign-in failed. Check your access key.');
    location.replace('/dashboard');
  } catch (error) { status.textContent = error.message; }
});

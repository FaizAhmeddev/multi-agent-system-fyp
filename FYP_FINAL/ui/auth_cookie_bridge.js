/** Cookie mutations happen on the same-origin HTTP server, never in document.cookie. */
export default function({ data, setStateValue }) {
    let disposed = false;
    const run = async () => {
        try {
            const base = data.base || '';
            const nonceResponse = await fetch(`${base}/_office/auth/nonce`, {
                credentials:'same-origin', cache:'no-store', redirect:'error', signal:AbortSignal.timeout(15000)
            });
            if (!nonceResponse.ok || !nonceResponse.headers.get('content-type')?.includes('application/json')) throw new Error('Secure sign-in is unavailable. Please contact your administrator.');
            const { csrf } = await nonceResponse.json();
            const response = await fetch(`${base}/_office/auth/${data.action}`, {
                method:'POST', credentials:'same-origin', cache:'no-store', redirect:'error', signal:AbortSignal.timeout(15000),
                headers:{'Content-Type':'application/json','X-Office-CSRF':csrf},
                body:JSON.stringify(data.action === 'handshake' ? { grant:data.grant } : {})
            });
            if (!response.ok) {
                const result = await response.json();
                throw new Error(result.error || 'Secure sign-in could not be completed.');
            }
            // A new WebSocket handshake supplies the HttpOnly cookie to st.context.
            // Native appearance is already persisted independently of authentication.
            if (!disposed) window.location.reload();
        } catch (error) {
            if (!disposed) setStateValue('error', error.message || 'Please retry signing in.');
        }
    };
    run();
    return () => { disposed = true; };
}

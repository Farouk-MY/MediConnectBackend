"""
Custom WebRTC Video Call HTML Template

Self-contained HTML page with peer-to-peer WebRTC video calling.
Uses WebSocket signaling via the backend VideoCallManager.
No third-party dependencies — pure WebRTC.
"""

VIDEO_CALL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body {
        width: 100%; height: 100%;
        overflow: hidden; background: #0a0a1a;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    /* Remote video — fills entire screen */
    #remoteVideo {
        position: absolute;
        top: 0; left: 0;
        width: 100%; height: 100%;
        object-fit: cover;
        background: #0a0a1a;
        z-index: 1;
    }

    /* Local video — small preview in corner */
    #localVideo {
        position: absolute;
        top: 16px; right: 16px;
        width: 100px; height: 140px;
        object-fit: cover;
        border-radius: 16px;
        border: 2px solid rgba(139, 92, 246, 0.6);
        z-index: 20;
        background: #1a1a2e;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    }

    /* Connection status overlay */
    #statusOverlay {
        position: absolute;
        top: 0; left: 0;
        width: 100%; height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        z-index: 10;
        background: radial-gradient(ellipse at center, #1a1a3e 0%, #0a0a1a 70%);
        transition: opacity 0.5s ease;
    }
    #statusOverlay.hidden {
        opacity: 0;
        pointer-events: none;
    }

    .status-icon {
        width: 80px; height: 80px;
        border-radius: 50%;
        background: linear-gradient(135deg, #8B5CF6, #6D28D9);
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 24px;
        box-shadow: 0 0 60px rgba(139, 92, 246, 0.4);
        animation: breathe 3s ease-in-out infinite;
    }
    .status-icon svg {
        width: 36px; height: 36px;
        fill: white;
    }
    .status-text {
        color: rgba(255,255,255,0.9);
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 8px;
    }
    .status-sub {
        color: rgba(255,255,255,0.4);
        font-size: 14px;
    }

    @keyframes breathe {
        0%, 100% { transform: scale(1); box-shadow: 0 0 40px rgba(139,92,246,0.3); }
        50% { transform: scale(1.08); box-shadow: 0 0 80px rgba(139,92,246,0.5); }
    }
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    .spinner {
        width: 32px; height: 32px;
        border: 3px solid rgba(255,255,255,0.1);
        border-top-color: #8B5CF6;
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin-top: 20px;
    }
</style>
</head>
<body>

<video id="remoteVideo" autoplay playsinline></video>
<video id="localVideo" autoplay playsinline muted></video>

<div id="statusOverlay">
    <div class="status-icon">
        <svg viewBox="0 0 24 24"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
    </div>
    <p class="status-text" id="statusText">Connecting...</p>
    <p class="status-sub" id="statusSub">Setting up secure connection</p>
    <div class="spinner" id="spinner"></div>
</div>

<script>
// ============ CONFIGURATION ============
const params = new URLSearchParams(window.location.search);
const ROOM_ID = params.get('roomId') || '';
const TOKEN = params.get('token') || '';
const DISPLAY_NAME = decodeURIComponent(params.get('displayName') || 'User');
const ROLE = params.get('role') || 'patient';

// Derive WebSocket URL from current page origin
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_BASE = wsProtocol + '//' + window.location.host + '/ws/video';

// STUN servers for NAT traversal
const ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun2.l.google.com:19302' },
    { urls: 'stun:stun3.l.google.com:19302' },
];

// ============ STATE ============
let localStream = null;
let peerConnection = null;
let websocket = null;
let makingOffer = false;
let ignoreOffer = false;
let isSettingRemoteAnswer = false;
let peerJoined = false;

// ============ REACT NATIVE BRIDGE ============
function sendToRN(data) {
    try {
        if (window.ReactNativeWebView) {
            window.ReactNativeWebView.postMessage(JSON.stringify(data));
        }
    } catch(e) {}
}

// ============ UI UPDATES ============
function setStatus(status, text, sub) {
    const overlay = document.getElementById('statusOverlay');
    const textEl = document.getElementById('statusText');
    const subEl = document.getElementById('statusSub');
    const spinner = document.getElementById('spinner');

    if (status === 'connected') {
        overlay.classList.add('hidden');
    } else {
        overlay.classList.remove('hidden');
        textEl.textContent = text || 'Connecting...';
        subEl.textContent = sub || '';
        spinner.style.display = status === 'error' ? 'none' : 'block';
    }
    sendToRN({ type: 'status', status: status });
}

// ============ MEDIA ============
async function initLocalMedia() {
    try {
        localStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'user',
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 30 }
            },
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });
        document.getElementById('localVideo').srcObject = localStream;
        sendToRN({ type: 'media-ready' });
        return true;
    } catch (err) {
        setStatus('error', 'Camera access denied', 'Please allow camera & microphone access');
        sendToRN({ type: 'error', message: 'Camera/microphone access denied' });
        return false;
    }
}

// ============ PEER CONNECTION ============
function createPeerConnection() {
    if (peerConnection) {
        peerConnection.close();
    }

    peerConnection = new RTCPeerConnection({ iceServers: ICE_SERVERS });

    // Add local tracks
    if (localStream) {
        localStream.getTracks().forEach(track => {
            peerConnection.addTrack(track, localStream);
        });
    }

    // ICE candidates → send to peer via signaling
    peerConnection.onicecandidate = (event) => {
        if (event.candidate && websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(JSON.stringify({
                type: 'signal',
                data: { type: 'ice-candidate', candidate: event.candidate }
            }));
        }
    };

    // Received remote video/audio track
    peerConnection.ontrack = (event) => {
        const remoteVideo = document.getElementById('remoteVideo');
        if (event.streams && event.streams[0]) {
            remoteVideo.srcObject = event.streams[0];
        }
    };

    // Connection state monitoring
    peerConnection.onconnectionstatechange = () => {
        const state = peerConnection.connectionState;
        switch (state) {
            case 'connected':
                setStatus('connected');
                sendToRN({ type: 'peer-stream-connected' });
                break;
            case 'disconnected':
                setStatus('reconnecting', 'Reconnecting...', 'Connection interrupted');
                sendToRN({ type: 'peer-disconnected' });
                break;
            case 'failed':
                // Attempt ICE restart
                peerConnection.restartIce();
                setStatus('reconnecting', 'Reconnecting...', 'Attempting to restore connection');
                break;
            case 'closed':
                sendToRN({ type: 'peer-disconnected' });
                break;
        }
    };

    peerConnection.oniceconnectionstatechange = () => {
        if (peerConnection.iceConnectionState === 'failed') {
            peerConnection.restartIce();
        }
    };

    return peerConnection;
}

// ============ SIGNALING ============
async function createAndSendOffer() {
    if (!peerConnection || makingOffer) return;
    makingOffer = true;
    try {
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(JSON.stringify({
                type: 'signal',
                data: { type: 'offer', sdp: peerConnection.localDescription }
            }));
        }
    } catch (err) {
        console.error('Offer creation error:', err);
    } finally {
        makingOffer = false;
    }
}

async function handleSignal(data) {
    if (!peerConnection) createPeerConnection();

    try {
        if (data.type === 'offer') {
            // Glare handling: if we're also making an offer
            const readyForOffer = !makingOffer &&
                (peerConnection.signalingState === 'stable' || isSettingRemoteAnswer);

            const offerCollision = !readyForOffer;
            // "Polite" peer (patient) yields, "impolite" peer (doctor) ignores
            ignoreOffer = ROLE === 'doctor' && offerCollision;
            if (ignoreOffer) return;

            await peerConnection.setRemoteDescription(new RTCSessionDescription(data.sdp));
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);

            websocket.send(JSON.stringify({
                type: 'signal',
                data: { type: 'answer', sdp: peerConnection.localDescription }
            }));

        } else if (data.type === 'answer') {
            isSettingRemoteAnswer = true;
            try {
                await peerConnection.setRemoteDescription(new RTCSessionDescription(data.sdp));
            } finally {
                isSettingRemoteAnswer = false;
            }

        } else if (data.type === 'ice-candidate') {
            if (data.candidate) {
                try {
                    await peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
                } catch (err) {
                    if (!ignoreOffer) console.error('ICE candidate error:', err);
                }
            }
        }
    } catch (err) {
        console.error('Signal handling error:', err);
    }
}

// ============ WEBSOCKET ============
function connectWebSocket() {
    setStatus('connecting', 'Connecting...', 'Setting up secure connection');

    const wsUrl = WS_BASE + '/' + ROOM_ID +
        '?token=' + encodeURIComponent(TOKEN) +
        '&role=' + encodeURIComponent(ROLE) +
        '&display_name=' + encodeURIComponent(DISPLAY_NAME);

    websocket = new WebSocket(wsUrl);

    websocket.onopen = () => {
        setStatus('waiting', 'Waiting for participant...', 'The other person will appear when they join');
        sendToRN({ type: 'ws-connected' });

        // Keep-alive ping
        setInterval(() => {
            if (websocket.readyState === WebSocket.OPEN) {
                websocket.send(JSON.stringify({ type: 'ping' }));
            }
        }, 25000);
    };

    websocket.onmessage = async (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch(e) { return; }

        switch (message.type) {
            case 'room_state':
                // Peer is already in the room
                if (message.participants && message.participants.length > 0) {
                    peerJoined = true;
                    const peer = message.participants[0];
                    sendToRN({
                        type: 'peer-joined',
                        displayName: peer.display_name,
                        role: peer.role
                    });
                    setStatus('connecting', 'Connecting call...', 'Establishing peer connection');
                    // We joined after them — create offer
                    await createAndSendOffer();
                }
                break;

            case 'participant_joined':
                peerJoined = true;
                sendToRN({
                    type: 'peer-joined',
                    displayName: message.display_name,
                    role: message.role
                });
                setStatus('connecting', 'Connecting call...', 'Establishing peer connection');
                // They joined after us — create offer
                await createAndSendOffer();
                break;

            case 'participant_left':
                peerJoined = false;
                sendToRN({ type: 'peer-left' });
                setStatus('waiting', 'Participant left', 'Waiting for them to reconnect...');
                // Reset peer connection for potential reconnection
                document.getElementById('remoteVideo').srcObject = null;
                if (peerConnection) {
                    peerConnection.close();
                    peerConnection = null;
                }
                createPeerConnection();
                break;

            case 'signal':
                await handleSignal(message.data || {});
                break;

            case 'pong':
                break;

            default:
                break;
        }
    };

    websocket.onclose = (event) => {
        sendToRN({ type: 'ws-disconnected' });
        if (event.code !== 1000 && event.code !== 4001) {
            setStatus('reconnecting', 'Connection lost', 'Reconnecting...');
            setTimeout(() => {
                if (!websocket || websocket.readyState === WebSocket.CLOSED) {
                    connectWebSocket();
                }
            }, 3000);
        }
    };

    websocket.onerror = () => {
        sendToRN({ type: 'ws-error' });
    };
}

// ============ CONTROLS (called from React Native) ============
function toggleMute() {
    if (!localStream) return;
    const audioTrack = localStream.getAudioTracks()[0];
    if (audioTrack) {
        audioTrack.enabled = !audioTrack.enabled;
        sendToRN({ type: 'mute-changed', muted: !audioTrack.enabled });
    }
}

function toggleCamera() {
    if (!localStream) return;
    const videoTrack = localStream.getVideoTracks()[0];
    if (videoTrack) {
        videoTrack.enabled = !videoTrack.enabled;
        // Show/hide local video preview
        document.getElementById('localVideo').style.opacity = videoTrack.enabled ? '1' : '0.3';
        sendToRN({ type: 'camera-changed', off: !videoTrack.enabled });
    }
}

function endCall() {
    if (localStream) {
        localStream.getTracks().forEach(t => t.stop());
        localStream = null;
    }
    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }
    if (websocket) {
        websocket.close(1000);
        websocket = null;
    }
    document.getElementById('localVideo').srcObject = null;
    document.getElementById('remoteVideo').srcObject = null;
    sendToRN({ type: 'call-ended' });
}

// Listen for commands from React Native
function handleRNMessage(event) {
    let msg;
    try { msg = JSON.parse(event.data); } catch(e) { return; }
    switch (msg.type) {
        case 'toggleMute': toggleMute(); break;
        case 'toggleCamera': toggleCamera(); break;
        case 'endCall': endCall(); break;
    }
}
document.addEventListener('message', handleRNMessage);
window.addEventListener('message', handleRNMessage);

// ============ STARTUP ============
(async function main() {
    sendToRN({ type: 'status', status: 'initializing' });

    const mediaOk = await initLocalMedia();
    if (!mediaOk) return;

    createPeerConnection();
    connectWebSocket();
})();
</script>
</body>
</html>
"""

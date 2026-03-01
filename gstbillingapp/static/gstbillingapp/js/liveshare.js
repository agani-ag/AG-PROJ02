/**
 * GST Sync - LiveShare Module
 * Bi-directional screen sharing + video/audio communication using PeerJS (WebRTC)
 *
 * Features:
 *   - Screen sharing (host shares screen)
 *   - Webcam video (both host & viewer see each other's face)
 *   - Microphone audio (both can speak bi-directionally)
 *   - Room code system for easy joining
 *   - Multiple active rooms discovery
 */

const LiveShare = (() => {
    // ─── State ───────────────────────────────────────────
    let peer = null;
    let connections = {};         // peerId -> { dataConn, mediaCall, screenCall }
    let localScreenStream = null;
    let localCamStream = null;
    let roomId = null;
    let isHost = false;
    let hostPeerId = null;
    let userName = 'User';

    // ─── Callbacks ───────────────────────────────────────
    let _onStatusChange = null;
    let _onRemoteScreen = null;
    let _onRemoteCam = null;
    let _onRemoteCamRemoved = null;
    let _onPeerJoined = null;
    let _onPeerLeft = null;
    let _onRoomList = null;
    let _onError = null;

    // ─── Helpers ─────────────────────────────────────────
    function generateRoomId() {
        const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
        let code = '';
        for (let i = 0; i < 6; i++) code += chars.charAt(Math.floor(Math.random() * chars.length));
        return code;
    }

    function emit(cb, ...args) { if (cb) cb(...args); }

    function makePeerId(prefix, room, suffix) {
        return `gstsync-${prefix}-${room}${suffix ? '-' + suffix : ''}`;
    }

    // ─── Get User Media ──────────────────────────────────
    async function getCameraAndMic(videoEnabled = true, audioEnabled = true) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: videoEnabled ? { width: { ideal: 320 }, height: { ideal: 240 }, facingMode: 'user' } : false,
                audio: audioEnabled ? { echoCancellation: true, noiseSuppression: true } : false,
            });
            localCamStream = stream;
            return stream;
        } catch (err) {
            console.warn('Camera/Mic access denied:', err.message);
            // Try audio only
            if (videoEnabled) {
                try {
                    const audioOnly = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
                    localCamStream = audioOnly;
                    return audioOnly;
                } catch (e) {
                    console.warn('Audio also denied:', e.message);
                }
            }
            return null;
        }
    }

    async function getScreenStream() {
        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: { cursor: 'always' },
                audio: false,
            });
            localScreenStream = stream;
            // Auto-stop if user clicks browser's "Stop sharing" button
            stream.getVideoTracks()[0].onended = () => {
                stopScreenShare();
            };
            return stream;
        } catch (err) {
            console.warn('Screen share denied:', err.message);
            return null;
        }
    }

    // ═══════════════════════════════════════════════════════
    //  HOST: Create a room and share screen + cam/mic
    // ═══════════════════════════════════════════════════════
    async function createRoom(options = {}) {
        isHost = true;
        roomId = generateRoomId();
        userName = options.userName || 'Host';
        const peerId = makePeerId('host', roomId);

        emit(_onStatusChange, 'initializing', 'Setting up room...');

        return new Promise((resolve, reject) => {
            peer = new Peer(peerId, { debug: options.debug || 0 });

            peer.on('open', async () => {
                emit(_onStatusChange, 'room-created', `Room ${roomId} created.`);

                // Get screen share
                const screenStream = await getScreenStream();
                if (!screenStream) {
                    emit(_onStatusChange, 'no-screen', 'Screen sharing was cancelled. Room is still active for cam/mic.');
                }

                // Get camera & mic
                const camStream = await getCameraAndMic(
                    options.video !== false,
                    options.audio !== false
                );

                emit(_onStatusChange, 'waiting', 'Waiting for viewers to join...');
                resolve({ roomId, screenStream, camStream });
            });

            // Incoming data connection from viewer
            peer.on('connection', (dataConn) => {
                handleDataConnection(dataConn);
            });

            // Incoming media call from viewer (their cam/mic)
            peer.on('call', (call) => {
                handleIncomingCall(call);
            });

            peer.on('error', (err) => {
                console.error('Host PeerJS error:', err);
                if (err.type === 'unavailable-id') {
                    // Room ID conflict, regenerate
                    roomId = generateRoomId();
                    emit(_onError, 'Room ID conflict. Retrying...');
                    peer.destroy();
                    createRoom(options).then(resolve).catch(reject);
                } else {
                    emit(_onError, err.message);
                    reject(err);
                }
            });

            peer.on('disconnected', () => {
                if (isHost) {
                    emit(_onStatusChange, 'reconnecting', 'Reconnecting...');
                    peer.reconnect();
                }
            });
        });
    }

    function handleDataConnection(dataConn) {
        const peerId = dataConn.peer;
        if (!connections[peerId]) connections[peerId] = {};
        connections[peerId].dataConn = dataConn;

        dataConn.on('open', () => {
            // Send room info
            dataConn.send({ type: 'room-info', roomId, hostName: userName });
            emit(_onPeerJoined, peerId, connections[peerId].peerName || 'Viewer');
            emit(_onStatusChange, 'viewer-joined', 'A viewer has joined.');

            // Send screen stream to the viewer
            if (localScreenStream && peer) {
                const screenCall = peer.call(peerId, localScreenStream, { metadata: { type: 'screen' } });
                connections[peerId].screenCall = screenCall;
            }

            // Send cam/mic stream to the viewer
            if (localCamStream && peer) {
                const camCall = peer.call(peerId, localCamStream, { metadata: { type: 'camera' } });
                connections[peerId].camCall = camCall;
            }
        });

        dataConn.on('data', (data) => {
            if (data.type === 'viewer-info') {
                connections[peerId].peerName = data.name;
                emit(_onPeerJoined, peerId, data.name);
            }
        });

        dataConn.on('close', () => {
            const name = connections[peerId]?.peerName || 'Viewer';
            delete connections[peerId];
            emit(_onPeerLeft, peerId, name);
            emit(_onRemoteCamRemoved, peerId);
            emit(_onStatusChange, 'viewer-left', `${name} has left.`);
        });
    }

    function handleIncomingCall(call) {
        const peerId = call.peer;
        const meta = call.metadata || {};

        // Answer with our stream (or empty)
        if (meta.type === 'camera') {
            // Viewer is sending their camera
            call.answer(localCamStream || new MediaStream());
            call.on('stream', (remoteStream) => {
                emit(_onRemoteCam, peerId, remoteStream, connections[peerId]?.peerName || 'Viewer');
            });
            call.on('close', () => {
                emit(_onRemoteCamRemoved, peerId);
            });
            if (!connections[peerId]) connections[peerId] = {};
            connections[peerId].viewerCamCall = call;
        }
    }

    // ═══════════════════════════════════════════════════════
    //  VIEWER: Join a room by code
    // ═══════════════════════════════════════════════════════
    async function joinRoom(code, options = {}) {
        isHost = false;
        roomId = code.toUpperCase().trim();
        userName = options.userName || 'Viewer';
        hostPeerId = makePeerId('host', roomId);
        const viewerPeerId = makePeerId('viewer', roomId, Date.now().toString());

        emit(_onStatusChange, 'connecting', 'Connecting to room...');

        // Get camera & mic for the viewer
        const camStream = await getCameraAndMic(
            options.video !== false,
            options.audio !== false
        );

        return new Promise((resolve, reject) => {
            peer = new Peer(viewerPeerId, { debug: options.debug || 0 });

            peer.on('open', () => {
                // Data connection to host
                const dataConn = peer.connect(hostPeerId, { reliable: true });

                dataConn.on('open', () => {
                    dataConn.send({ type: 'viewer-info', name: userName });
                    connections[hostPeerId] = { dataConn };
                    emit(_onStatusChange, 'connected', 'Connected to room!');

                    // Send our camera to the host
                    if (camStream) {
                        const camCall = peer.call(hostPeerId, camStream, { metadata: { type: 'camera' } });
                        camCall.on('stream', () => {}); // Host's response
                        connections[hostPeerId].viewerCamCall = camCall;
                    }

                    resolve({ roomId, camStream });
                });

                dataConn.on('data', (data) => {
                    if (data.type === 'room-info') {
                        connections[hostPeerId].hostName = data.hostName;
                    }
                });

                dataConn.on('close', () => {
                    emit(_onStatusChange, 'host-left', 'The host has ended the session.');
                    emit(_onRemoteScreen, null);
                    emit(_onRemoteCamRemoved, hostPeerId);
                });

                dataConn.on('error', (err) => {
                    emit(_onError, 'Connection error: ' + err.message);
                });

                // Timeout
                setTimeout(() => {
                    if (!dataConn.open) {
                        emit(_onError, 'Could not connect. Check the Room Code.');
                        cleanup();
                        reject(new Error('Connection timeout'));
                    }
                }, 12000);
            });

            // Receive calls from host (screen share + cam/mic)
            peer.on('call', (call) => {
                call.answer(camStream || new MediaStream());
                const meta = call.metadata || {};

                call.on('stream', (remoteStream) => {
                    if (meta.type === 'screen') {
                        emit(_onRemoteScreen, remoteStream);
                    } else if (meta.type === 'camera') {
                        emit(_onRemoteCam, hostPeerId, remoteStream, connections[hostPeerId]?.hostName || 'Host');
                    }
                });

                call.on('close', () => {
                    if (meta.type === 'screen') {
                        emit(_onRemoteScreen, null);
                    } else if (meta.type === 'camera') {
                        emit(_onRemoteCamRemoved, hostPeerId);
                    }
                });
            });

            peer.on('error', (err) => {
                console.error('Viewer PeerJS error:', err);
                if (err.type === 'peer-unavailable') {
                    emit(_onError, 'Room not found. Check the code and ensure the host is sharing.');
                } else {
                    emit(_onError, err.message);
                }
                reject(err);
            });
        });
    }

    // ─── Screen share toggle (host only) ─────────────────
    async function startScreenShare() {
        if (!isHost || !peer) return null;
        const stream = await getScreenStream();
        if (!stream) return null;

        // Send to all connected viewers
        Object.keys(connections).forEach(pid => {
            const screenCall = peer.call(pid, stream, { metadata: { type: 'screen' } });
            connections[pid].screenCall = screenCall;
        });

        emit(_onStatusChange, 'screen-sharing', 'Screen sharing started.');
        return stream;
    }

    function stopScreenShare() {
        if (localScreenStream) {
            localScreenStream.getTracks().forEach(t => t.stop());
            localScreenStream = null;
        }
        // Close screen calls
        Object.values(connections).forEach(c => {
            if (c.screenCall) { c.screenCall.close(); c.screenCall = null; }
        });
        emit(_onStatusChange, 'screen-stopped', 'Screen sharing stopped.');
    }

    // ─── Camera/Mic toggles ─────────────────────────────
    function toggleCamera(enabled) {
        if (localCamStream) {
            localCamStream.getVideoTracks().forEach(t => { t.enabled = enabled; });
        }
    }

    function toggleMic(enabled) {
        if (localCamStream) {
            localCamStream.getAudioTracks().forEach(t => { t.enabled = enabled; });
        }
    }

    // ─── Leave / Cleanup ─────────────────────────────────
    function leaveRoom() {
        if (localScreenStream) {
            localScreenStream.getTracks().forEach(t => t.stop());
            localScreenStream = null;
        }
        if (localCamStream) {
            localCamStream.getTracks().forEach(t => t.stop());
            localCamStream = null;
        }
        cleanup();
        emit(_onStatusChange, 'left', 'You have left the session.');
    }

    function cleanup() {
        Object.values(connections).forEach(c => {
            if (c.dataConn) c.dataConn.close();
            if (c.mediaCall) c.mediaCall.close();
            if (c.screenCall) c.screenCall.close();
            if (c.camCall) c.camCall.close();
            if (c.viewerCamCall) c.viewerCamCall.close();
        });
        connections = {};
        if (peer) { peer.destroy(); peer = null; }
        isHost = false;
        roomId = null;
    }

    // ─── Public API ──────────────────────────────────────
    return {
        // Actions
        createRoom,
        joinRoom,
        leaveRoom,
        startScreenShare,
        stopScreenShare,
        toggleCamera,
        toggleMic,
        getCameraAndMic,

        // Getters
        getRoomId: () => roomId,
        isHosting: () => isHost,
        getLocalCamStream: () => localCamStream,
        getLocalScreenStream: () => localScreenStream,

        // Event setters
        onStatusChange:    (cb) => { _onStatusChange = cb; },
        onRemoteScreen:    (cb) => { _onRemoteScreen = cb; },
        onRemoteCam:       (cb) => { _onRemoteCam = cb; },
        onRemoteCamRemoved:(cb) => { _onRemoteCamRemoved = cb; },
        onPeerJoined:      (cb) => { _onPeerJoined = cb; },
        onPeerLeft:        (cb) => { _onPeerLeft = cb; },
        onError:           (cb) => { _onError = cb; },
    };
})();

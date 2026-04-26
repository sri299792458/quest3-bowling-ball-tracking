package com.questbowling.standalone;

import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.view.Surface;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.net.InetSocketAddress;
import java.net.Socket;

public final class StandaloneVideoEncoderPlugin {
    private static final String MIME_TYPE = "video/avc";
    private static final int LIVE_CONNECT_TIMEOUT_MS = 1000;
    private static final byte[] STREAM_PACKET_MAGIC = new byte[] { 'Q', 'B', 'L', 'S' };
    private static final int STREAM_PACKET_VERSION = 1;
    private static final int STREAM_PACKET_TYPE_SESSION_START = 1;
    private static final int STREAM_PACKET_TYPE_SAMPLE = 2;
    private static final int STREAM_PACKET_TYPE_SESSION_END = 3;
    private static final int STREAM_PACKET_TYPE_CODEC_CONFIG = 4;
    private static final int STREAM_SAMPLE_FLAG_KEYFRAME = 1;
    private static final byte[] ANNEX_B_START_CODE = new byte[] { 0, 0, 0, 1 };

    static {
        System.loadLibrary("standaloneencodersurfacebridge");
    }

    private final Object gate = new Object();

    private MediaCodec codec;
    private MediaMuxer muxer;
    private Surface inputSurface;
    private MediaCodec.BufferInfo bufferInfo;
    private Thread drainThread;
    private boolean running;
    private boolean stopping;
    private boolean muxerStarted;
    private int trackIndex = -1;
    private long writtenSampleCount;
    private String outputPath = "";
    private String lastError = "";
    private int configuredWidth;
    private int configuredHeight;
    private int configuredFps;
    private int configuredBitrateKbps;
    private Socket liveStreamSocket;
    private OutputStream liveStreamOutput;
    private String liveStreamHost = "";
    private int liveStreamPort;
    private String liveStreamSessionId = "";
    private String liveStreamShotId = "";
    private long liveStreamSentSampleCount;
    private boolean liveStreamConnected;
    private String liveStreamLastError = "";
    private boolean liveCodecConfigSent;

    public boolean startSession(String outputPath, int width, int height, int fps, int bitrateKbps, float iFrameIntervalSeconds) {
        synchronized (gate) {
            if (running) {
                lastError = "already_running";
                return false;
            }

            try {
                prepareOutputPath(outputPath);

                bufferInfo = new MediaCodec.BufferInfo();
                codec = MediaCodec.createEncoderByType(MIME_TYPE);

                MediaFormat format = MediaFormat.createVideoFormat(MIME_TYPE, width, height);
                format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
                format.setInteger(MediaFormat.KEY_BIT_RATE, bitrateKbps * 1000);
                format.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
                format.setFloat(MediaFormat.KEY_I_FRAME_INTERVAL, iFrameIntervalSeconds);

                codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
                inputSurface = codec.createInputSurface();
                codec.start();

                muxer = new MediaMuxer(outputPath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
                trackIndex = -1;
                muxerStarted = false;
                writtenSampleCount = 0L;
                lastError = "";
                configuredWidth = width;
                configuredHeight = height;
                configuredFps = fps;
                configuredBitrateKbps = bitrateKbps;
                this.outputPath = outputPath;
                running = true;
                stopping = false;

                drainThread = new Thread(this::drainEncoderLoop, "StandaloneVideoEncoderDrain");
                drainThread.start();
                return true;
            } catch (Exception ex) {
                lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                releaseAllLocked();
                return false;
            }
        }
    }

    public boolean stopSession() {
        Thread threadToJoin;
        synchronized (gate) {
            if (!running || codec == null) {
                lastError = "not_running";
                return false;
            }

            try {
                stopping = true;
                codec.signalEndOfInputStream();
            } catch (Exception ex) {
                lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
            }

            threadToJoin = drainThread;
        }

        if (threadToJoin != null) {
            try {
                threadToJoin.join(5000L);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                synchronized (gate) {
                    lastError = "InterruptedException: " + ex.getMessage();
                }
            }
        }

        synchronized (gate) {
            boolean ok = running == false && lastError.isEmpty();
            if (running) {
                releaseAllLocked();
            }
            return ok;
        }
    }

    public void abortSession() {
        synchronized (gate) {
            lastError = "aborted";
            releaseAllLocked();
        }
    }

    public boolean isRunning() {
        synchronized (gate) {
            return running;
        }
    }

    public Surface getInputSurface() {
        synchronized (gate) {
            return inputSurface;
        }
    }

    public boolean connectLiveStream(String host, int port, String sessionId, String shotId) {
        synchronized (gate) {
            if (!running || codec == null) {
                liveStreamLastError = "encoder_not_running";
                return false;
            }

            try {
                closeLiveStreamLocked(false, "reset");
                liveStreamSocket = new Socket();
                liveStreamSocket.connect(new InetSocketAddress(host, port), LIVE_CONNECT_TIMEOUT_MS);
                liveStreamSocket.setTcpNoDelay(true);
                liveStreamOutput = liveStreamSocket.getOutputStream();
                liveStreamHost = host == null ? "" : host;
                liveStreamPort = port;
                liveStreamSessionId = sessionId == null ? "" : sessionId;
                liveStreamShotId = shotId == null ? "" : shotId;
                liveStreamSentSampleCount = 0L;
                liveStreamConnected = true;
                liveStreamLastError = "";
                liveCodecConfigSent = false;

                JSONObject payload = new JSONObject();
                payload.put("session_id", liveStreamSessionId);
                payload.put("shot_id", liveStreamShotId);
                payload.put("width", configuredWidth);
                payload.put("height", configuredHeight);
                payload.put("fps", configuredFps);
                payload.put("bitrate_kbps", configuredBitrateKbps);
                payload.put("codec", "h264");
                writeStreamPacketLocked(STREAM_PACKET_TYPE_SESSION_START, payload.toString().getBytes("UTF-8"));
                if (muxerStarted && codec != null) {
                    maybeWriteLiveCodecConfigLocked(codec.getOutputFormat());
                }
                return true;
            } catch (Exception ex) {
                liveStreamLastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                closeLiveStreamLocked(false, liveStreamLastError);
                return false;
            }
        }
    }

    public boolean disconnectLiveStream() {
        synchronized (gate) {
            if (!liveStreamConnected) {
                liveStreamLastError = "live_stream_not_connected";
                return false;
            }

            closeLiveStreamLocked(true, "manual_disconnect");
            return true;
        }
    }

    public String getStatusJson() {
        synchronized (gate) {
            JSONObject root = new JSONObject();
            try {
                root.put("status", running ? "running" : "idle");
                root.put("mime", MIME_TYPE);
                root.put("output_path", outputPath);
                root.put("width", configuredWidth);
                root.put("height", configuredHeight);
                root.put("fps", configuredFps);
                root.put("bitrate_kbps", configuredBitrateKbps);
                root.put("muxer_started", muxerStarted);
                root.put("written_sample_count", writtenSampleCount);
                root.put("stopping", stopping);
                root.put("last_error", lastError);
                root.put("live_stream_connected", liveStreamConnected);
                root.put("live_stream_host", liveStreamHost);
                root.put("live_stream_port", liveStreamPort);
                root.put("live_stream_session_id", liveStreamSessionId);
                root.put("live_stream_shot_id", liveStreamShotId);
                root.put("live_stream_sent_sample_count", liveStreamSentSampleCount);
                root.put("live_stream_last_error", liveStreamLastError);
            } catch (JSONException ex) {
                return "{\"status\":\"error\",\"message\":\"" + escapeJson(ex.getMessage()) + "\"}";
            }

            return root.toString();
        }
    }

    private void drainEncoderLoop() {
        boolean sawEndOfStream = false;

        while (!sawEndOfStream) {
            MediaCodec localCodec;
            MediaMuxer localMuxer;
            MediaCodec.BufferInfo localBufferInfo;

            synchronized (gate) {
                localCodec = codec;
                localMuxer = muxer;
                localBufferInfo = bufferInfo;
                if (localCodec == null || localMuxer == null || localBufferInfo == null) {
                    return;
                }
            }

            int outputBufferIndex;
            try {
                outputBufferIndex = localCodec.dequeueOutputBuffer(localBufferInfo, 10000L);
            } catch (Exception ex) {
                synchronized (gate) {
                    lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                    releaseAllLocked();
                }
                return;
            }

            if (outputBufferIndex == MediaCodec.INFO_TRY_AGAIN_LATER) {
                synchronized (gate) {
                    if (!running && !stopping) {
                        return;
                    }
                }
                continue;
            }

            if (outputBufferIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                synchronized (gate) {
                    if (muxerStarted) {
                        lastError = "output_format_changed_twice";
                        releaseAllLocked();
                        return;
                    }

                    try {
                        MediaFormat outputFormat = codec.getOutputFormat();
                        trackIndex = muxer.addTrack(outputFormat);
                        muxer.start();
                        muxerStarted = true;
                        maybeWriteLiveCodecConfigLocked(outputFormat);
                    } catch (Exception ex) {
                        lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                        releaseAllLocked();
                        return;
                    }
                }
                continue;
            }

            if (outputBufferIndex < 0) {
                continue;
            }

            ByteBuffer outputBuffer;
            try {
                outputBuffer = localCodec.getOutputBuffer(outputBufferIndex);
            } catch (Exception ex) {
                synchronized (gate) {
                    lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                    releaseAllLocked();
                }
                return;
            }

            if (outputBuffer == null) {
                localCodec.releaseOutputBuffer(outputBufferIndex, false);
                continue;
            }

            if ((localBufferInfo.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0) {
                localBufferInfo.size = 0;
            }

            if (localBufferInfo.size > 0) {
                synchronized (gate) {
                    if (!muxerStarted) {
                        lastError = "muxer_not_started_before_sample";
                        releaseAllLocked();
                        return;
                    }

                    try {
                        outputBuffer.position(localBufferInfo.offset);
                        outputBuffer.limit(localBufferInfo.offset + localBufferInfo.size);
                        muxer.writeSampleData(trackIndex, outputBuffer, localBufferInfo);
                        writtenSampleCount++;
                        maybeWriteLiveSampleLocked(outputBuffer, localBufferInfo);
                    } catch (Exception ex) {
                        lastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
                        releaseAllLocked();
                        return;
                    }
                }
            }

            sawEndOfStream = (localBufferInfo.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
            localCodec.releaseOutputBuffer(outputBufferIndex, false);
        }

        synchronized (gate) {
            releaseAllLocked();
        }
    }

    private void prepareOutputPath(String targetPath) throws IOException {
        File targetFile = new File(targetPath);
        File parent = targetFile.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("Failed to create parent directory for output.");
        }

        if (targetFile.exists() && !targetFile.delete()) {
            throw new IOException("Failed to overwrite existing output file.");
        }
    }

    private void releaseAllLocked() {
        running = false;
        stopping = false;
        muxerStarted = false;
        trackIndex = -1;
        closeLiveStreamLocked(true, "encoder_release");

        if (inputSurface != null) {
            try {
                inputSurface.release();
            } catch (Exception ignored) {
            }
            inputSurface = null;
        }

        if (codec != null) {
            try {
                codec.stop();
            } catch (Exception ignored) {
            }
            try {
                codec.release();
            } catch (Exception ignored) {
            }
            codec = null;
        }

        if (muxer != null) {
            try {
                muxer.stop();
            } catch (Exception ignored) {
            }
            try {
                muxer.release();
            } catch (Exception ignored) {
            }
            muxer = null;
        }

        bufferInfo = null;
        drainThread = null;
    }

    private void maybeWriteLiveSampleLocked(ByteBuffer outputBuffer, MediaCodec.BufferInfo localBufferInfo) {
        if (!liveStreamConnected || liveStreamOutput == null || localBufferInfo.size <= 0) {
            return;
        }

        try {
            ByteBuffer duplicate = outputBuffer.duplicate();
            duplicate.position(localBufferInfo.offset);
            duplicate.limit(localBufferInfo.offset + localBufferInfo.size);

            byte[] sampleBytes = new byte[localBufferInfo.size];
            duplicate.get(sampleBytes);

            int streamFlags = 0;
            if ((localBufferInfo.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0) {
                streamFlags |= STREAM_SAMPLE_FLAG_KEYFRAME;
            }

            ByteBuffer samplePayload = ByteBuffer.allocate(16 + sampleBytes.length).order(ByteOrder.LITTLE_ENDIAN);
            samplePayload.putLong(localBufferInfo.presentationTimeUs);
            samplePayload.putInt(streamFlags);
            samplePayload.putInt(sampleBytes.length);
            samplePayload.put(sampleBytes);
            writeStreamPacketLocked(STREAM_PACKET_TYPE_SAMPLE, samplePayload.array());
            liveStreamSentSampleCount++;
        } catch (Exception ex) {
            liveStreamLastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
            closeLiveStreamLocked(false, liveStreamLastError);
        }
    }

    private void maybeWriteLiveCodecConfigLocked(MediaFormat outputFormat) {
        if (!liveStreamConnected || liveStreamOutput == null || outputFormat == null || liveCodecConfigSent) {
            return;
        }

        try {
            byte[] codecConfig = buildCodecConfigAnnexB(outputFormat);
            if (codecConfig.length == 0) {
                return;
            }

            writeStreamPacketLocked(STREAM_PACKET_TYPE_CODEC_CONFIG, codecConfig);
            liveCodecConfigSent = true;
        } catch (Exception ex) {
            liveStreamLastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
            closeLiveStreamLocked(false, liveStreamLastError);
        }
    }

    private void writeStreamPacketLocked(int packetType, byte[] payload) throws IOException {
        if (liveStreamOutput == null) {
            throw new IOException("liveStreamOutput missing");
        }

        byte[] body = payload == null ? new byte[0] : payload;
        ByteBuffer header = ByteBuffer.allocate(10).order(ByteOrder.LITTLE_ENDIAN);
        header.put(STREAM_PACKET_MAGIC);
        header.put((byte) STREAM_PACKET_VERSION);
        header.put((byte) packetType);
        header.putInt(body.length);
        liveStreamOutput.write(header.array());
        if (body.length > 0) {
            liveStreamOutput.write(body);
        }
        liveStreamOutput.flush();
    }

    private void closeLiveStreamLocked(boolean sendSessionEnd, String reason) {
        if (sendSessionEnd && liveStreamConnected && liveStreamOutput != null) {
            try {
                JSONObject payload = new JSONObject();
                payload.put("session_id", liveStreamSessionId);
                payload.put("shot_id", liveStreamShotId);
                payload.put("reason", reason == null ? "stream_closed" : reason);
                writeStreamPacketLocked(STREAM_PACKET_TYPE_SESSION_END, payload.toString().getBytes("UTF-8"));
            } catch (Exception ex) {
                liveStreamLastError = ex.getClass().getSimpleName() + ": " + ex.getMessage();
            }
        }

        if (liveStreamOutput != null) {
            try {
                liveStreamOutput.close();
            } catch (Exception ignored) {
            }
            liveStreamOutput = null;
        }

        if (liveStreamSocket != null) {
            try {
                liveStreamSocket.close();
            } catch (Exception ignored) {
            }
            liveStreamSocket = null;
        }

        liveStreamConnected = false;
        liveStreamHost = "";
        liveStreamPort = 0;
        liveStreamSessionId = "";
        liveStreamShotId = "";
        liveCodecConfigSent = false;
    }

    private static byte[] buildCodecConfigAnnexB(MediaFormat format) {
        byte[] sps = readCodecConfigBuffer(format, "csd-0");
        byte[] pps = readCodecConfigBuffer(format, "csd-1");
        if (sps.length == 0 && pps.length == 0) {
            return new byte[0];
        }

        byte[] annexBSps = ensureAnnexBStartCode(sps);
        byte[] annexBPps = ensureAnnexBStartCode(pps);
        byte[] combined = new byte[annexBSps.length + annexBPps.length];
        System.arraycopy(annexBSps, 0, combined, 0, annexBSps.length);
        System.arraycopy(annexBPps, 0, combined, annexBSps.length, annexBPps.length);
        return combined;
    }

    private static byte[] readCodecConfigBuffer(MediaFormat format, String key) {
        ByteBuffer buffer = format.getByteBuffer(key);
        if (buffer == null) {
            return new byte[0];
        }

        ByteBuffer duplicate = buffer.duplicate();
        duplicate.position(0);
        byte[] data = new byte[duplicate.remaining()];
        duplicate.get(data);
        return data;
    }

    private static byte[] ensureAnnexBStartCode(byte[] data) {
        if (data == null || data.length == 0) {
            return new byte[0];
        }

        if (startsWithStartCode(data, 0)) {
            return data;
        }

        if (data.length > 4) {
            int declaredLength =
                    ((data[0] & 0xFF) << 24)
                            | ((data[1] & 0xFF) << 16)
                            | ((data[2] & 0xFF) << 8)
                            | (data[3] & 0xFF);
            if (declaredLength > 0 && declaredLength == data.length - 4) {
                byte[] converted = new byte[ANNEX_B_START_CODE.length + declaredLength];
                System.arraycopy(ANNEX_B_START_CODE, 0, converted, 0, ANNEX_B_START_CODE.length);
                System.arraycopy(data, 4, converted, ANNEX_B_START_CODE.length, declaredLength);
                return converted;
            }
        }

        byte[] prefixed = new byte[ANNEX_B_START_CODE.length + data.length];
        System.arraycopy(ANNEX_B_START_CODE, 0, prefixed, 0, ANNEX_B_START_CODE.length);
        System.arraycopy(data, 0, prefixed, ANNEX_B_START_CODE.length, data.length);
        return prefixed;
    }

    private static boolean startsWithStartCode(byte[] data, int offset) {
        if (data == null || data.length - offset < 4) {
            return false;
        }

        return data[offset] == 0
                && data[offset + 1] == 0
                && ((data[offset + 2] == 0 && data[offset + 3] == 1) || data[offset + 2] == 1);
    }

    private static String escapeJson(String value) {
        return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}

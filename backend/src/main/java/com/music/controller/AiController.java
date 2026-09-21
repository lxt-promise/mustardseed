package com.music.controller;

import com.music.common.Result;
import com.music.dto.AiChatRequest;
import com.music.service.AiService;
import com.music.service.AiServiceException;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;

/**
 * AI 大模型接口：同步对话 + SSE 流式对话。
 *
 * <p>完整路径（server.servlet.context-path=/api）：
 * <ul>
 *   <li>POST /api/ai/chat —— 同步，支持多轮历史</li>
 *   <li>GET  /api/ai/chat/stream?message=xxx —— SSE 流式（EventSource 可用）</li>
 * </ul>
 */
@RestController
@RequestMapping("/ai")
public class AiController {

    private static final Logger log = LoggerFactory.getLogger(AiController.class);

    /** SSE 超时 5 分钟。 */
    private static final long SSE_TIMEOUT_MS = 300_000L;

    private final AiService aiService;

    public AiController(AiService aiService) {
        this.aiService = aiService;
    }

    /**
     * 同步对话。
     */
    @PostMapping("/chat")
    public Result<Map<String, Object>> chat(@Valid @RequestBody AiChatRequest request) {
        try {
            String response = aiService.chat(request);
            return Result.success(Map.of("response", response));
        } catch (AiServiceException e) {
            log.warn("AI 同步对话失败：{}", e.getMessage());
            return Result.error(503, e.getMessage());
        }
    }

    /**
     * 流式对话（SSE）。浏览器可用 {@code new EventSource('/api/ai/chat/stream?message=...')}
     * 监听 {@code message} 事件增量接收文本，{@code error} 事件携带错误信息。
     */
    @GetMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamChat(@RequestParam String message) {
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);

        AiChatRequest request = new AiChatRequest();
        request.setMessage(message);

        // 订阅放在守护线程，避免 SDK 首包阻塞占用 Tomcat 请求线程
        Thread worker = new Thread(() ->
                aiService.streamChat(request).subscribe(
                        content -> {
                            try {
                                emitter.send(SseEmitter.event().name("message").data(content));
                            } catch (java.io.IOException e) {
                                emitter.completeWithError(e);
                            }
                        },
                        error -> {
                            log.warn("AI 流式响应错误：{}", error.getMessage());
                            try {
                                emitter.send(SseEmitter.event()
                                        .name("error")
                                        .data(error.getMessage() == null ? "AI 服务异常" : error.getMessage()));
                            } catch (Exception ignored) {
                                // 连接可能已断开
                            }
                            emitter.complete();
                        },
                        emitter::complete
                ), "ai-sse-worker");
        worker.setDaemon(true);
        worker.start();

        return emitter;
    }
}

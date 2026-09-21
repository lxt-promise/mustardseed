package com.music.service;

import ai.z.openapi.ZhipuAiClient;
import ai.z.openapi.service.model.ChatCompletionCreateParams;
import ai.z.openapi.service.model.ChatCompletionResponse;
import ai.z.openapi.service.model.ChatMessage;
import ai.z.openapi.service.model.ChatMessageRole;
import ai.z.openapi.service.model.ChatThinking;
import com.music.config.AiProperties;
import com.music.dto.AiChatRequest;
import com.music.dto.AiMessage;
import io.reactivex.rxjava3.core.Flowable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * 大模型调用服务（智谱 GLM）。
 *
 * <p>标准用法：
 * <pre>
 *   // 同步
 *   String reply = aiService.chat(request);
 *   // 流式（SSE 推送）
 *   aiService.streamChat(request).subscribe(chunk -> emitter.send(chunk), ...);
 * </pre>
 *
 * <p>客户端懒加载：未配置 api-key 时应用仍可正常启动，仅调用 AI 接口时给出明确提示。
 */
@Service
public class AiService {

    private static final Logger log = LoggerFactory.getLogger(AiService.class);

    /** 历史消息中允许透传的角色（system 统一走 systemPrompt，避免伪造）。 */
    private static final Set<String> ALLOWED_HISTORY_ROLES = Set.of("user", "assistant");

    private static final int MAX_RETRIES = 3;
    private static final long BASE_DELAY_MS = 2000L;

    private final AiProperties properties;

    private volatile ZhipuAiClient client;

    public AiService(AiProperties properties) {
        this.properties = properties;
    }

    // ============================================================== 客户端

    private ZhipuAiClient client() {
        ZhipuAiClient existing = client;
        if (existing != null) {
            return existing;
        }
        synchronized (this) {
            if (client == null) {
                if (!properties.isEnabled()) {
                    throw new AiServiceException("AI 功能已被配置关闭（music.ai.enabled=false）");
                }
                if (!StringUtils.hasText(properties.getApiKey())) {
                    throw new AiServiceException("未配置 AI API Key，请在 application.yml 的 music.ai.api-key 或环境变量 AI_API_KEY 中设置");
                }
                try {
                    client = ZhipuAiClient.builder().ofZHIPU()
                            .apiKey(properties.getApiKey())
                            .build();
                    log.info("智谱 AI 客户端初始化成功，模型：{}", properties.getModel());
                } catch (Exception e) {
                    throw new AiServiceException("智谱 AI 客户端初始化失败：" + e.getMessage(), e);
                }
            }
            return client;
        }
    }

    // ============================================================== 消息构建

    /**
     * 组装发给大模型的消息列表：系统提示词 + 历史对话 + 本轮用户消息。
     */
    private List<ChatMessage> buildMessages(AiChatRequest request) {
        List<ChatMessage> messages = new ArrayList<>();

        String systemPrompt = StringUtils.hasText(request.getSystemPrompt())
                ? request.getSystemPrompt().trim()
                : properties.getSystemPrompt();
        if (StringUtils.hasText(systemPrompt)) {
            messages.add(ChatMessage.builder()
                    .role(ChatMessageRole.SYSTEM.value())
                    .content(systemPrompt)
                    .build());
        }

        if (request.getHistory() != null) {
            for (AiMessage m : request.getHistory()) {
                if (m == null || !StringUtils.hasText(m.getRole()) || !StringUtils.hasText(m.getContent())) {
                    continue;
                }
                String role = m.getRole().trim().toLowerCase();
                if (!ALLOWED_HISTORY_ROLES.contains(role)) {
                    log.warn("忽略非法历史消息角色：{}", m.getRole());
                    continue;
                }
                messages.add(ChatMessage.builder()
                        .role(role)
                        .content(m.getContent())
                        .build());
            }
        }

        messages.add(ChatMessage.builder()
                .role(ChatMessageRole.USER.value())
                .content(request.getMessage())
                .build());
        return messages;
    }

    private ChatCompletionCreateParams buildRequest(AiChatRequest request, boolean stream) {
        var builder = ChatCompletionCreateParams.builder()
                .model(properties.getModel())
                .messages(buildMessages(request))
                .maxTokens(properties.getMaxTokens())
                .temperature(properties.getTemperature())
                .stream(stream);
        if (properties.isThinkingEnabled()) {
            builder.thinking(ChatThinking.builder().type("enabled").build());
        }
        return builder.build();
    }

    // ============================================================== 同步调用

    /**
     * 同步对话，带 429 限流指数退避重试。
     *
     * @return 模型回复文本
     * @throws AiServiceException 重试耗尽或远端不可用
     */
    public String chat(AiChatRequest request) {
        ChatCompletionCreateParams params = buildRequest(request, false);

        Exception lastError = null;
        for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
            try {
                ChatCompletionResponse response = client().chat().createChatCompletion(params);
                if (response.isSuccess()) {
                    Object reply = response.getData().getChoices().get(0).getMessage();
                    if (reply instanceof ChatMessage chatMsg) {
                        Object content = chatMsg.getContent();
                        return content != null ? content.toString() : "";
                    }
                    return reply == null ? "" : reply.toString();
                }
                // SDK 在限流(429)/瞬时错误时可能返回 isSuccess=false 且 msg 仅为
                // "Call Failed"，无法按错误码区分，统一按指数退避重试到上限。
                String msg = response.getMsg();
                lastError = new AiServiceException("AI 服务返回失败：" + msg);
                log.warn("AI 请求失败（第 {}/{} 次）：{}", attempt, MAX_RETRIES, msg);
                if (attempt < MAX_RETRIES && backoff(attempt)) {
                    continue;
                }
                throw (AiServiceException) lastError;
            } catch (AiServiceException e) {
                throw e;
            } catch (Exception e) {
                lastError = e;
                log.warn("AI 请求异常（第 {}/{} 次）：{}", attempt, MAX_RETRIES, e.getMessage());
                boolean rateLimited = e.getMessage() != null && e.getMessage().contains("429");
                if (attempt < MAX_RETRIES && rateLimited && backoff(attempt)) {
                    continue;
                }
                throw new AiServiceException("AI 服务调用失败：" + e.getMessage(), e);
            }
        }
        throw new AiServiceException("AI 服务暂时不可用，请稍后重试", lastError);
    }

    /**
     * 指数退避等待，返回 false 表示等待被中断。
     */
    private boolean backoff(int attempt) {
        long delay = BASE_DELAY_MS * (long) Math.pow(2, attempt - 1);
        log.info("触发限流，等待 {}ms 后重试", delay);
        try {
            TimeUnit.MILLISECONDS.sleep(delay);
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    // ============================================================== 流式调用

    /**
     * 流式对话，每个元素是一个增量文本片段（chunk）。
     * 调用方通过 RxJava 订阅后转发给 SSE 客户端。
     */
    public Flowable<String> streamChat(AiChatRequest request) {
        ChatCompletionCreateParams params = buildRequest(request, true);

        ChatCompletionResponse response;
        try {
            response = client().chat().createChatCompletion(params);
        } catch (Exception e) {
            return Flowable.error(new AiServiceException("AI 流式请求失败：" + e.getMessage(), e));
        }

        if (!response.isSuccess()) {
            return Flowable.error(new AiServiceException("AI 流式请求被拒绝：" + response.getMsg()));
        }

        return response.getFlowable()
                .map(data -> {
                    if (data.getChoices() == null || data.getChoices().isEmpty()) {
                        return "";
                    }
                    var delta = data.getChoices().get(0).getDelta();
                    return delta != null && delta.getContent() != null ? delta.getContent() : "";
                })
                .filter(StringUtils::hasText);
    }
}

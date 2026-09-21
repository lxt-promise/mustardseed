package com.music.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 大模型（智谱 GLM）调用配置，对应 application.yml 中 {@code music.ai} 段。
 */
@Data
@ConfigurationProperties(prefix = "music.ai")
public class AiProperties {

    /** 是否启用 AI 功能；关闭或未配置 api-key 时接口返回明确提示。 */
    private boolean enabled = true;

    /** 智谱 API Key（建议通过环境变量 AI_API_KEY 注入）。 */
    private String apiKey;

    /** 模型名称，如 glm-4.7-flash。 */
    private String model = "glm-4.7-flash";

    /** 默认系统提示词，请求中传 systemPrompt 可覆盖。 */
    private String systemPrompt;

    /** 单次回答最大 token 数。 */
    private int maxTokens = 4096;

    /** 采样温度 0~1。 */
    private float temperature = 0.8f;

    /** 是否开启深度思考（GLM-4.x thinking 参数）。 */
    private boolean thinkingEnabled = true;
}

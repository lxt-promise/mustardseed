package com.music.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.List;

/**
 * AI 对话请求体。
 */
@Data
public class AiChatRequest {

    /** 本轮用户消息。 */
    @NotBlank(message = "message 不能为空")
    private String message;

    /** 覆盖默认系统提示词（可选）。 */
    private String systemPrompt;

    /** 多轮对话历史（可选），按时间正序排列。 */
    @Valid
    private List<AiMessage> history;
}

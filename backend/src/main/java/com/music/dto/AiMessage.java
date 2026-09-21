package com.music.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 多轮对话中的一条历史消息。
 *
 * @param role    角色：user / assistant（system 请用请求级 systemPrompt）
 * @param content 文本内容
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiMessage {

    @NotBlank(message = "role 不能为空")
    private String role;

    @NotBlank(message = "content 不能为空")
    private String content;
}

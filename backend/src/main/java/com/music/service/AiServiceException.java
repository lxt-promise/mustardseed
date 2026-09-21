package com.music.service;

/**
 * AI 大模型调用异常：未配置、限流重试耗尽、远端错误等。
 */
public class AiServiceException extends RuntimeException {

    public AiServiceException(String message) {
        super(message);
    }

    public AiServiceException(String message, Throwable cause) {
        super(message, cause);
    }
}

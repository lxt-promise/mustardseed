package com.music;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
@MapperScan("com.music.mapper")
public class MusicApplication {
    public static void main(String[] args) {
        SpringApplication.run(MusicApplication.class, args);
        System.out.println("\n========== 音乐管家后端启动成功 ==========");
        System.out.println("API 地址: http://localhost:8080/api");
        System.out.println("H2控制台: http://localhost:8080/api/h2-console");
        System.out.println("===========================================\n");
    }
}

package com.photocloud;

import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@ConfigurationPropertiesScan
@EnableScheduling
public class PhotoServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(PhotoServerApplication.class, args);
    }
}

package com.ilyesabidi.secureapi.config;

import io.awspring.cloud.sqs.config.SqsMessageListenerContainerFactory;
import io.awspring.cloud.sqs.operations.SqsTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sqs.SqsAsyncClient;

import java.net.URI;

@Configuration
public class SqsConfig {

    @Value("${aws.region:eu-west-1}")
    private String region;

    @Value("${sqs.endpoint:}")
    private String sqsEndpoint;

    @Bean
    public SqsAsyncClient sqsAsyncClient() {
        var builder = SqsAsyncClient.builder()
                .region(Region.of(region));

        if (!sqsEndpoint.isBlank()) {
            // LocalStack or custom endpoint
            builder.endpointOverride(URI.create(sqsEndpoint))
                   .credentialsProvider(StaticCredentialsProvider.create(
                           AwsBasicCredentials.create("test", "test")));
        }

        return builder.build();
    }

    @Bean
    public SqsTemplate sqsTemplate(SqsAsyncClient sqsAsyncClient) {
        return SqsTemplate.newTemplate(sqsAsyncClient);
    }

    @Bean
    public SqsMessageListenerContainerFactory<Object> defaultSqsListenerContainerFactory(SqsAsyncClient sqsAsyncClient) {
        return SqsMessageListenerContainerFactory.builder()
                .sqsAsyncClient(sqsAsyncClient)
                .build();
    }
}

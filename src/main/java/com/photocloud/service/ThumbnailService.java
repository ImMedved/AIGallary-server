package com.photocloud.service;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;

@Service
public class ThumbnailService {

    static final int THUMBNAIL_SIZE = 128;

    public byte[] generate(byte[] originalContent) {
        try {
            BufferedImage source = ImageIO.read(new ByteArrayInputStream(originalContent));

            if (source == null) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unsupported image format");
            }

            int width = source.getWidth();
            int height = source.getHeight();
            double scale = Math.max(
                    (double) THUMBNAIL_SIZE / width,
                    (double) THUMBNAIL_SIZE / height
            );

            int scaledWidth = Math.max(THUMBNAIL_SIZE, (int) Math.round(width * scale));
            int scaledHeight = Math.max(THUMBNAIL_SIZE, (int) Math.round(height * scale));

            BufferedImage result = new BufferedImage(
                    THUMBNAIL_SIZE,
                    THUMBNAIL_SIZE,
                    BufferedImage.TYPE_INT_RGB
            );

            Graphics2D graphics = result.createGraphics();
            graphics.setColor(Color.WHITE);
            graphics.fillRect(0, 0, THUMBNAIL_SIZE, THUMBNAIL_SIZE);
            graphics.setRenderingHint(
                    RenderingHints.KEY_INTERPOLATION,
                    RenderingHints.VALUE_INTERPOLATION_BILINEAR
            );
            graphics.setRenderingHint(
                    RenderingHints.KEY_RENDERING,
                    RenderingHints.VALUE_RENDER_QUALITY
            );

            int x = (THUMBNAIL_SIZE - scaledWidth) / 2;
            int y = (THUMBNAIL_SIZE - scaledHeight) / 2;

            graphics.drawImage(source, x, y, scaledWidth, scaledHeight, null);
            graphics.dispose();

            ByteArrayOutputStream output = new ByteArrayOutputStream();
            ImageIO.write(result, "jpg", output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unable to build thumbnail", exception);
        }
    }
}

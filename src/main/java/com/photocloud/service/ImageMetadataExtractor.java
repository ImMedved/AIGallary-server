package com.photocloud.service;

import com.drew.imaging.ImageMetadataReader;
import com.drew.imaging.ImageProcessingException;
import com.drew.lang.GeoLocation;
import com.drew.metadata.Metadata;
import com.drew.metadata.exif.ExifIFD0Directory;
import com.drew.metadata.exif.ExifSubIFDDirectory;
import com.drew.metadata.exif.GpsDirectory;
import org.springframework.stereotype.Service;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.time.Instant;
import java.util.Date;
import java.util.StringJoiner;

@Service
public class ImageMetadataExtractor {

    public ExtractedImageMetadata extract(byte[] imageBytes) {
        Integer width = null;
        Integer height = null;

        try {
            BufferedImage image = ImageIO.read(new ByteArrayInputStream(imageBytes));

            if (image != null) {
                width = image.getWidth();
                height = image.getHeight();
            }
        } catch (IOException ignored) {
        }

        try {
            Metadata metadata = ImageMetadataReader.readMetadata(new ByteArrayInputStream(imageBytes));
            ExifIFD0Directory ifd0 = metadata.getFirstDirectoryOfType(ExifIFD0Directory.class);
            ExifSubIFDDirectory subIfd = metadata.getFirstDirectoryOfType(ExifSubIFDDirectory.class);
            GpsDirectory gpsDirectory = metadata.getFirstDirectoryOfType(GpsDirectory.class);

            String cameraMake = trim(ifd0 == null ? null : ifd0.getString(ExifIFD0Directory.TAG_MAKE));
            String cameraModel = trim(ifd0 == null ? null : ifd0.getString(ExifIFD0Directory.TAG_MODEL));
            String deviceName = buildDeviceName(cameraMake, cameraModel);
            Date originalDate = subIfd == null ? null : subIfd.getDateOriginal();
            Instant takenAt = originalDate == null ? null : originalDate.toInstant();
            GeoLocation location = gpsDirectory == null ? null : gpsDirectory.getGeoLocation();
            String orientation = ifd0 == null ? null : trim(ifd0.getDescription(ExifIFD0Directory.TAG_ORIENTATION));

            return new ExtractedImageMetadata(
                    width,
                    height,
                    takenAt,
                    cameraMake,
                    cameraModel,
                    deviceName,
                    location == null ? null : location.getLatitude(),
                    location == null ? null : location.getLongitude(),
                    orientation
            );
        } catch (ImageProcessingException | IOException exception) {
            return new ExtractedImageMetadata(width, height, null, null, null, null, null, null, null);
        }
    }

    private String buildDeviceName(String cameraMake, String cameraModel) {
        StringJoiner joiner = new StringJoiner(" ");

        if (cameraMake != null && !cameraMake.isBlank()) {
            joiner.add(cameraMake);
        }

        if (cameraModel != null && !cameraModel.isBlank()) {
            joiner.add(cameraModel);
        }

        String value = joiner.toString().trim();
        return value.isBlank() ? null : value;
    }

    private String trim(String value) {
        if (value == null) {
            return null;
        }

        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}

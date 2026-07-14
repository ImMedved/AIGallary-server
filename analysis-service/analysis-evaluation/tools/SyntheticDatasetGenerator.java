import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.awt.image.ConvolveOp;
import java.awt.image.Kernel;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Random;

public final class SyntheticDatasetGenerator {
    private static final Path ROOT = Path.of("analysis-service", "analysis-evaluation");
    private static final Path IMAGES_DIR = ROOT.resolve("images");
    private static final Path EXPECTED_DIR = ROOT.resolve("expected");

    private record Sample(String fileName, String imageKind, String expectedText, List<String> requiredTags, List<String> allowedTags, List<String> forbiddenTags, String notes) {}

    public static void main(String[] args) throws Exception {
        Files.createDirectories(IMAGES_DIR);
        Files.createDirectories(EXPECTED_DIR);
        List<Sample> samples = new ArrayList<>();

        generateScreenshots(samples);
        generateMemes(samples);
        generateDocuments(samples);
        generatePhotosWithText(samples);
        generateOrdinaryPhotos(samples);
        generateDifficult(samples);

        if (samples.size() != 100) {
            throw new IllegalStateException("Expected 100 samples, got " + samples.size());
        }

        writeIndex(samples);
        System.out.println("Generated samples: " + samples.size());
    }

    private static void generateScreenshots(List<Sample> samples) throws IOException {
        for (int index = 1; index <= 20; index++) {
            String title = "SETTINGS PANEL " + index;
            String line1 = "PROFILE AUTO SAVE ENABLED";
            String line2 = "SYNC STATUS OK " + (10 + index);
            BufferedImage image = canvas(1280, 720, new Color(242, 245, 250));
            Graphics2D g = graphics(image);
            drawWindow(g, image.getWidth(), image.getHeight(), title, line1, line2);
            if (index % 4 == 0) {
                drawCodePane(g, 720, 160, false);
            }
            if (index % 5 == 0) {
                drawChatPane(g, 760, 150);
            }
            g.dispose();

            String fileName = String.format(Locale.ROOT, "screenshot-%02d.png", index);
            writeSample(image, fileName);
            String expectedText = index % 4 == 0
                ? title + " IMPORT MEDIA SERVICE RETURN STATUS OK"
                : title + " " + line1 + " " + line2;
            List<String> allowed = new ArrayList<>(List.of("document", "web page", "code screenshot", "chat screenshot", "latin text"));
            if (index % 5 == 0) {
                allowed.add("message");
            }
            samples.add(new Sample(fileName, "screenshot", expectedText, List.of("screenshot", "text"), allowed, List.of("receipt", "car"), "Synthetic screenshot baseline sample"));
        }
    }

    private static void generateMemes(List<Sample> samples) throws IOException {
        for (int index = 1; index <= 20; index++) {
            BufferedImage image = canvas(1024, 1024, new Color(35, 45, 62));
            Graphics2D g = graphics(image);
            drawGradientBackground(g, image.getWidth(), image.getHeight(), new Color(16 + index * 3, 72, 122), new Color(230, 160 - index, 48 + index * 2));
            drawFaceLikeScene(g, image.getWidth(), image.getHeight(), index);
            String top = "WHEN BUILD CACHE HITS " + index;
            String bottom = "AND DOCKER FINALLY BEHAVES";
            drawMemeCaption(g, image.getWidth(), top, bottom);
            g.dispose();

            String fileName = String.format(Locale.ROOT, "meme-%02d.png", index);
            writeSample(image, fileName);
            samples.add(new Sample(fileName, "meme", top + " " + bottom, List.of("meme", "text"), List.of("people", "photo", "latin text"), List.of("receipt"), "Synthetic meme baseline sample"));
        }
    }

    private static void generateDocuments(List<Sample> samples) throws IOException {
        for (int index = 1; index <= 15; index++) {
            BufferedImage image = canvas(900, 1280, new Color(252, 250, 244));
            Graphics2D g = graphics(image);
            drawDocument(g, image.getWidth(), image.getHeight(), index);
            g.dispose();

            String fileName = String.format(Locale.ROOT, "document-%02d.png", index);
            writeSample(image, fileName);
            String expectedText = "INVOICE " + index + " CLIENT SMART GALLERY TOTAL " + (120 + index) + " EUR";
            List<String> required = index % 3 == 0 ? List.of("document", "text") : List.of("document", "text");
            List<String> allowed = index % 3 == 0 ? List.of("receipt", "latin text") : List.of("latin text");
            samples.add(new Sample(fileName, "document", expectedText, required, allowed, List.of("car", "animal"), "Synthetic document or scan sample"));
        }
    }

    private static void generatePhotosWithText(List<Sample> samples) throws IOException {
        for (int index = 1; index <= 15; index++) {
            BufferedImage image = canvas(1280, 860, new Color(140, 190, 230));
            Graphics2D g = graphics(image);
            drawLandscape(g, image.getWidth(), image.getHeight(), index);
            String sign = "OPEN AIR MARKET " + index;
            drawBillboard(g, 180 + index * 10, 240 + (index % 3) * 40, 520, 150, sign);
            g.dispose();

            String fileName = String.format(Locale.ROOT, "photo-text-%02d.png", index);
            writeSample(image, fileName);
            samples.add(new Sample(fileName, "natural_photo_with_text", sign, List.of("photo", "text"), List.of("latin text", "people", "outdoor"), List.of("receipt"), "Synthetic natural photo with visible text"));
        }
    }

    private static void generateOrdinaryPhotos(List<Sample> samples) throws IOException {
        for (int index = 1; index <= 20; index++) {
            BufferedImage image = canvas(1280, 860, new Color(100, 150, 180));
            Graphics2D g = graphics(image);
            drawLandscape(g, image.getWidth(), image.getHeight(), index + 20);
            if (index % 2 == 0) {
                drawAnimalShape(g, 850, 520, index);
            } else {
                drawVehicleShape(g, 760, 540, index);
            }
            g.dispose();

            String fileName = String.format(Locale.ROOT, "photo-plain-%02d.png", index);
            writeSample(image, fileName);
            List<String> allowed = index % 2 == 0 ? List.of("animal", "photo") : List.of("transport", "photo");
            samples.add(new Sample(fileName, "ordinary_photo", "", List.of("photo"), allowed, List.of("receipt", "document", "text"), "Synthetic ordinary photo without visible text"));
        }
    }

    private static void generateDifficult(List<Sample> samples) throws IOException {
        for (int index = 1; index <= 10; index++) {
            BufferedImage image = canvas(1000, 700, new Color(70, 78, 92));
            Graphics2D g = graphics(image);
            drawGradientBackground(g, image.getWidth(), image.getHeight(), new Color(42, 48, 66), new Color(122, 90, 70));
            drawBillboard(g, 180, 240, 640, 120, "LOW LIGHT SAMPLE " + index);
            addNoise(image, 18L * index, 28);
            if (index % 2 == 0) {
                blur(image);
            }
            g.dispose();

            String fileName = String.format(Locale.ROOT, "difficult-%02d.png", index);
            writeSample(image, fileName);
            samples.add(new Sample(fileName, "difficult", "LOW LIGHT SAMPLE " + index, List.of("photo", "text"), List.of("difficult", "latin text"), List.of("receipt"), "Synthetic difficult or low-quality sample"));
        }
    }

    private static BufferedImage canvas(int width, int height, Color background) {
        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = image.createGraphics();
        g.setColor(background);
        g.fillRect(0, 0, width, height);
        g.dispose();
        return image;
    }

    private static Graphics2D graphics(BufferedImage image) {
        Graphics2D g = image.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        return g;
    }

    private static void drawGradientBackground(Graphics2D g, int width, int height, Color top, Color bottom) {
        GradientPaint gradient = new GradientPaint(0, 0, top, 0, height, bottom);
        g.setPaint(gradient);
        g.fillRect(0, 0, width, height);
    }

    private static void drawWindow(Graphics2D g, int width, int height, String title, String line1, String line2) {
        g.setColor(new Color(222, 228, 236));
        g.fillRoundRect(90, 70, width - 180, height - 140, 26, 26);
        g.setColor(new Color(32, 40, 56));
        g.fillRoundRect(90, 70, width - 180, 72, 26, 26);
        g.setColor(Color.WHITE);
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 30));
        g.drawString(title, 140, 116);
        g.setColor(new Color(72, 86, 108));
        g.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 26));
        g.drawString(line1, 150, 210);
        g.drawString(line2, 150, 254);
        for (int row = 0; row < 5; row++) {
            g.setColor(new Color(248, 250, 252));
            g.fillRoundRect(150, 300 + row * 70, 430, 46, 14, 14);
            g.setColor(new Color(112, 126, 144));
            g.drawString("OPTION " + (row + 1) + " ENABLED", 170, 332 + row * 70);
        }
    }

    private static void drawCodePane(Graphics2D g, int x, int y, boolean dark) {
        g.setColor(dark ? new Color(28, 31, 40) : new Color(246, 248, 252));
        g.fillRoundRect(x, y, 420, 320, 18, 18);
        g.setColor(dark ? new Color(138, 221, 255) : new Color(62, 72, 92));
        g.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 22));
        g.drawString("import media.service", x + 24, y + 60);
        g.drawString("return status ok", x + 24, y + 104);
        g.drawString("cache_hits += 1", x + 24, y + 148);
        g.drawString("if retry_after > 0", x + 24, y + 192);
    }

    private static void drawChatPane(Graphics2D g, int x, int y) {
        g.setColor(new Color(247, 248, 252));
        g.fillRoundRect(x, y, 380, 340, 24, 24);
        g.setColor(new Color(72, 84, 108));
        g.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 22));
        drawChatBubble(g, x + 20, y + 26, 250, 60, new Color(225, 233, 255), "BUILD OK");
        drawChatBubble(g, x + 100, y + 110, 240, 60, new Color(218, 248, 229), "SHIP TODAY");
        drawChatBubble(g, x + 20, y + 194, 260, 60, new Color(225, 233, 255), "CACHE READY");
    }

    private static void drawChatBubble(Graphics2D g, int x, int y, int width, int height, Color color, String text) {
        g.setColor(color);
        g.fill(new RoundRectangle2D.Double(x, y, width, height, 20, 20));
        g.setColor(new Color(52, 60, 78));
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 22));
        g.drawString(text, x + 18, y + 38);
    }

    private static void drawFaceLikeScene(Graphics2D g, int width, int height, int seed) {
        g.setColor(new Color(245, 216, 188));
        g.fillOval(300, 250, 420, 420);
        g.setColor(new Color(64, 44, 34));
        g.fillOval(405, 380, 34, 48);
        g.fillOval(575, 380, 34, 48);
        g.setStroke(new BasicStroke(8f));
        g.drawArc(430, 470, 170, 90, 190, 160);
        g.setColor(new Color(40 + seed, 26, 20));
        g.fillArc(270, 170, 500, 240, 0, 180);
    }

    private static void drawMemeCaption(Graphics2D g, int width, String top, String bottom) {
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 48));
        drawOutlinedText(g, top, width / 2, 90);
        drawOutlinedText(g, bottom, width / 2, 960);
    }

    private static void drawOutlinedText(Graphics2D g, String text, int centerX, int y) {
        FontMetrics metrics = g.getFontMetrics();
        int x = centerX - metrics.stringWidth(text) / 2;
        g.setColor(Color.BLACK);
        for (int dx = -3; dx <= 3; dx++) {
            for (int dy = -3; dy <= 3; dy++) {
                if (dx != 0 || dy != 0) {
                    g.drawString(text, x + dx, y + dy);
                }
            }
        }
        g.setColor(Color.WHITE);
        g.drawString(text, x, y);
    }

    private static void drawDocument(Graphics2D g, int width, int height, int index) {
        g.setColor(Color.WHITE);
        g.fillRoundRect(70, 50, width - 140, height - 100, 18, 18);
        g.setColor(new Color(90, 96, 112));
        g.setStroke(new BasicStroke(2f));
        g.drawRoundRect(70, 50, width - 140, height - 100, 18, 18);

        g.setColor(new Color(36, 42, 56));
        g.setFont(new Font(Font.SERIF, Font.BOLD, 42));
        g.drawString("INVOICE " + index, 120, 150);
        g.setFont(new Font(Font.SERIF, Font.PLAIN, 28));
        g.drawString("CLIENT SMART GALLERY", 120, 215);
        g.drawString("TOTAL " + (120 + index) + " EUR", 120, 255);
        for (int row = 0; row < 12; row++) {
            g.drawString("LINE ITEM " + (row + 1) + " SERVICE DELIVERY", 120, 340 + row * 58);
        }
    }

    private static void drawLandscape(Graphics2D g, int width, int height, int seed) {
        drawGradientBackground(g, width, height, new Color(120, 180, 232), new Color(240, 230, 180));
        g.setColor(new Color(84, 136, 82));
        g.fillOval(-80, height - 280, 520, 320);
        g.fillOval(240, height - 260, 620, 300);
        g.fillOval(760, height - 300, 560, 340);
        g.setColor(new Color(90 + seed % 40, 70 + seed % 30, 54));
        g.fillRect(300, 250, 28, 260);
        g.fillOval(220, 140, 200, 160);
        g.fillRect(940, 280, 30, 210);
        g.fillOval(860, 180, 180, 140);
    }

    private static void drawBillboard(Graphics2D g, int x, int y, int width, int height, String text) {
        g.setColor(new Color(76, 60, 46));
        g.fillRect(x + 40, y + height, 18, 120);
        g.fillRect(x + width - 58, y + height, 18, 120);
        g.setColor(new Color(248, 236, 184));
        g.fillRoundRect(x, y, width, height, 18, 18);
        g.setColor(new Color(78, 68, 42));
        g.setStroke(new BasicStroke(3f));
        g.drawRoundRect(x, y, width, height, 18, 18);
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 42));
        FontMetrics metrics = g.getFontMetrics();
        int textX = x + (width - metrics.stringWidth(text)) / 2;
        int textY = y + height / 2 + 15;
        g.drawString(text, textX, textY);
    }

    private static void drawAnimalShape(Graphics2D g, int x, int y, int index) {
        g.setColor(new Color(78, 58, 34));
        g.fillOval(x, y, 170, 90);
        g.fillOval(x + 120, y - 40, 85, 70);
        g.fillRect(x + 20, y + 70, 18, 90);
        g.fillRect(x + 60, y + 70, 18, 90);
        g.fillRect(x + 120, y + 70, 18, 90);
        g.fillRect(x + 150, y + 70, 18, 90);
        g.fillOval(x + 182, y - 16, 12, 12);
        if (index % 3 == 0) {
            g.setColor(new Color(240, 236, 220));
            g.fillOval(x + 18, y + 16, 20, 20);
        }
    }

    private static void drawVehicleShape(Graphics2D g, int x, int y, int index) {
        g.setColor(new Color(180, 40 + index * 2, 42));
        g.fillRoundRect(x, y, 240, 90, 26, 26);
        g.fillRoundRect(x + 48, y - 42, 122, 56, 18, 18);
        g.setColor(new Color(28, 34, 42));
        g.fillOval(x + 34, y + 70, 48, 48);
        g.fillOval(x + 158, y + 70, 48, 48);
    }

    private static void addNoise(BufferedImage image, long seed, int amplitude) {
        Random random = new Random(seed);
        for (int y = 0; y < image.getHeight(); y++) {
            for (int x = 0; x < image.getWidth(); x++) {
                int rgb = image.getRGB(x, y);
                int r = ((rgb >> 16) & 0xff) + random.nextInt(amplitude * 2 + 1) - amplitude;
                int g = ((rgb >> 8) & 0xff) + random.nextInt(amplitude * 2 + 1) - amplitude;
                int b = (rgb & 0xff) + random.nextInt(amplitude * 2 + 1) - amplitude;
                int noisy = (clamp(r) << 16) | (clamp(g) << 8) | clamp(b);
                image.setRGB(x, y, noisy);
            }
        }
    }

    private static void blur(BufferedImage image) {
        float[] kernel = {
            1f / 16f, 2f / 16f, 1f / 16f,
            2f / 16f, 4f / 16f, 2f / 16f,
            1f / 16f, 2f / 16f, 1f / 16f
        };
        BufferedImage source = new BufferedImage(image.getWidth(), image.getHeight(), BufferedImage.TYPE_INT_RGB);
        Graphics2D g = source.createGraphics();
        g.drawImage(image, 0, 0, null);
        g.dispose();
        ConvolveOp op = new ConvolveOp(new Kernel(3, 3, kernel), ConvolveOp.EDGE_NO_OP, null);
        op.filter(source, image);
    }

    private static int clamp(int value) {
        return Math.max(0, Math.min(255, value));
    }

    private static void writeSample(BufferedImage image, String fileName) throws IOException {
        ImageIO.write(image, "png", IMAGES_DIR.resolve(fileName).toFile());
    }

    private static void writeIndex(List<Sample> samples) throws IOException {
        StringBuilder index = new StringBuilder();
        index.append("[\n");
        for (int i = 0; i < samples.size(); i++) {
            Sample sample = samples.get(i);
            writeExpected(sample);
            index.append("  {\"file\":\"").append(sample.fileName()).append("\",\"kind\":\"").append(sample.imageKind()).append("\"}");
            if (i + 1 < samples.size()) {
                index.append(',');
            }
            index.append('\n');
        }
        index.append("]\n");
        Files.writeString(ROOT.resolve("dataset-index.json"), index.toString(), StandardCharsets.UTF_8);
    }

    private static void writeExpected(Sample sample) throws IOException {
        StringBuilder json = new StringBuilder();
        json.append("{\n");
        json.append("  \"imageKind\": \"").append(escape(sample.imageKind())).append("\",\n");
        json.append("  \"expectedText\": \"").append(escape(sample.expectedText())).append("\",\n");
        json.append("  \"requiredTags\": ").append(array(sample.requiredTags())).append(",\n");
        json.append("  \"allowedTags\": ").append(array(sample.allowedTags())).append(",\n");
        json.append("  \"forbiddenTags\": ").append(array(sample.forbiddenTags())).append(",\n");
        json.append("  \"notes\": \"").append(escape(sample.notes())).append("\"\n");
        json.append("}\n");
        Path target = EXPECTED_DIR.resolve(sample.fileName().replace(".png", ".json"));
        Files.writeString(target, json.toString(), StandardCharsets.UTF_8);
    }

    private static String array(List<String> values) {
        StringBuilder builder = new StringBuilder();
        builder.append('[');
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) {
                builder.append(", ");
            }
            builder.append('"').append(escape(values.get(i))).append('"');
        }
        builder.append(']');
        return builder.toString();
    }

    private static String escape(String value) {
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n");
    }
}

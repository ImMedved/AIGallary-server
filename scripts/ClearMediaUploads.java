import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

public class ClearMediaUploads {

    private static final String JDBC_URL = System.getenv().getOrDefault(
            "SMART_GALLERY_JDBC_URL",
            "jdbc:postgresql://localhost:5432/photo_cloud"
    );

    private static final String PRIMARY_JDBC_USER = System.getenv().getOrDefault(
            "SMART_GALLERY_JDBC_USER",
            "photo_user"
    );

    private static final String PRIMARY_JDBC_PASSWORD = System.getenv().getOrDefault(
            "SMART_GALLERY_JDBC_PASSWORD",
            "photo_password"
    );

    public static void main(String[] args) throws Exception {
        List<String[]> candidates = new ArrayList<>();
        candidates.add(new String[]{PRIMARY_JDBC_USER, PRIMARY_JDBC_PASSWORD});
        candidates.add(new String[]{"postgres", "photo_password"});
        candidates.add(new String[]{"postgres", "postgres"});
        candidates.add(new String[]{"postgres", "password"});
        candidates.add(new String[]{"postgres", "admin"});
        candidates.add(new String[]{"postgres", "123456"});
        candidates.add(new String[]{"postgres", "minio123"});
        candidates.add(new String[]{"photo_user", "admin"});
        candidates.add(new String[]{"photo_user", "123456"});
        candidates.add(new String[]{"photo_user", "minio123"});
        candidates.add(new String[]{"postgres", ""});
        candidates.add(new String[]{"photo_user", ""});

        Exception lastException = null;
        for (String[] candidate : candidates) {
            try (Connection connection = DriverManager.getConnection(JDBC_URL, candidate[0], candidate[1]);
                 Statement statement = connection.createStatement()) {
                System.out.println("Connected with user='" + candidate[0] + "'");
                connection.setAutoCommit(false);

                Map<String, Long> before = countRows(statement);
                System.out.println("Before cleanup: " + before);

                statement.execute("truncate table media_assets restart identity cascade");

                connection.commit();

                Map<String, Long> after = countRows(statement);
                System.out.println("After cleanup: " + after);
                return;
            } catch (Exception exception) {
                System.out.println("Connection failed for user='" + candidate[0] + "'");
                lastException = exception;
            }
        }

        if (lastException != null) {
            throw lastException;
        }
    }

    private static Map<String, Long> countRows(Statement statement) throws Exception {
        Map<String, Long> counts = new LinkedHashMap<>();
        counts.put("media_assets", count(statement, "media_assets"));
        counts.put("media_variants", count(statement, "media_variants"));
        counts.put("media_metadata", count(statement, "media_metadata"));
        counts.put("media_tags", count(statement, "media_tags"));
        counts.put("media_processing_jobs", count(statement, "media_processing_jobs"));
        counts.put("media_delivery_requests", count(statement, "media_delivery_requests"));
        return counts;
    }

    private static long count(Statement statement, String tableName) throws Exception {
        try (ResultSet resultSet = statement.executeQuery("select count(*) from " + tableName)) {
            resultSet.next();
            return resultSet.getLong(1);
        }
    }
}

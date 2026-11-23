package campus.cats;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

public final class CaptureFile extends ContentProvider {
    static final String AUTH = "campus.cats.capture";
    private static File folder(Context ctx) { return new File(ctx.getCacheDir(), "camera"); }
    static Uri create(Context ctx) throws IOException {
        File dir = folder(ctx);
        if (!dir.isDirectory() && !dir.mkdir()) throw new IOException("Camera directory unavailable");
        File[] previous = dir.listFiles();
        if (previous != null) for (File item : previous) {
            if (item.lastModified() < System.currentTimeMillis()-86400000L) item.delete();
        }
        File image = File.createTempFile("cat-", ".jpg", dir);
        return new Uri.Builder().scheme("content").authority(AUTH).appendPath(image.getName()).build();
    }
    private File image(Uri uri) {
        String name = uri.getLastPathSegment();
        if (!AUTH.equals(uri.getAuthority()) || name == null || !name.matches("cat-[0-9A-Za-z_-]+\\.jpg")
            || uri.getPathSegments().size() != 1) throw new IllegalArgumentException("Invalid image");
        return new File(folder(getContext()), name);
    }
    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) { image(uri); return "image/jpeg"; }
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        File file = image(uri);
        if (!file.isFile()) throw new FileNotFoundException();
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.parseMode(mode));
    }
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort) {
        File f = image(uri);
        String[] columns = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE} : projection;
        MatrixCursor result = new MatrixCursor(columns);
        MatrixCursor.RowBuilder row = result.newRow();
        for (String key : columns) row.add(OpenableColumns.DISPLAY_NAME.equals(key) ? f.getName() : OpenableColumns.SIZE.equals(key) ? f.length() : null);
        return result;
    }
    @Override public Uri insert(Uri u, ContentValues v) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri u,String s,String[] a) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri u,ContentValues v,String s,String[] a) { throw new UnsupportedOperationException(); }
}
